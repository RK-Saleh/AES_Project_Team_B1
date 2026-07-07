import cv2
import json
import time
import threading
from datetime import datetime
import paho.mqtt.client as mqtt
from ultralytics import YOLO
from flask import Flask, Response

# ==========================================
# 1. CONFIGURATION
# ==========================================
MODEL_NAME = 'best_ncnn_model'
CONFIDENCE_THRESHOLD = 0.50

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC_STATE = "airspace/surveillance/state"               # Pi      -> dashboard
MQTT_TOPIC_TELEMETRY = "airspace/node2/telemetry"              # Arduino -> Pi
MQTT_TOPIC_ALERT = "airspace/alert"                            # Pi      -> ESP32

SAFE_CLASSES   = {'civilian aircraft', 'civilian helicopter', 'civilian car'}
HAZARD_CLASSES = {'military aircraft', 'military helicopter', 'drone', 'fixed wing uav', 'multi-rotor', 'military tank', 'military truck'}
COLOR_MAP = {'SAFE': (0, 255, 0), 'HAZARDOUS': (0, 0, 255)}

CAMERA_PATH = "/dev/v4l/by-id/usb-Image+_UGREEN_Camera_4K_LL-0000000001-video-index0"
STREAM_FPS  = 30                                               # target stream rate

# ==========================================
# 2. SHARED STATE
# ==========================================
# Raw camera frames — capture thread writes, all others read
raw_frame = None
raw_lock  = threading.Lock()

# Annotated frame served by Flask — stream_loop writes, Flask reads
global_frame = None
frame_lock   = threading.Lock()

# Latest YOLO results — inference thread writes, stream_loop reads
last_boxes   = []      # [{'bbox':(x1,y1,x2,y2), 'label':str, 'threat_level':str, 'confidence':float}]
last_status  = "CLEAR"
last_inf_fps = 0.0
boxes_lock   = threading.Lock()

# Telemetry from Arduino — MQTT callback writes, stream_loop reads
latest_distance = None
latest_speed    = None
tel_lock        = threading.Lock()

# ==========================================
# 3. CAMERA CAPTURE THREAD
# ==========================================
def capture_loop(cap):
    """
    Runs in its own thread.  Continuously drains the V4L2 kernel buffer
    so the inference thread always picks up the freshest frame.
    cap.read() blocks for ~33 ms waiting for the next hardware frame,
    so this loop naturally paces at the camera's native rate without spin.
    """
    global raw_frame
    while True:
        ret, frame = cap.read()
        if ret:
            with raw_lock:
                raw_frame = frame

# ==========================================
# 4. STREAM COMPOSITING THREAD  ← NEW KEY FIX
# ==========================================
def stream_loop():
    """
    Runs at STREAM_FPS (30 Hz), completely independent of YOLO speed.

    Each iteration:
      1. Grabs the latest raw camera frame.
      2. Redraws the most recently computed YOLO bounding boxes on it.
      3. Adds the HUD.
      4. Writes to global_frame for Flask to serve.

    Result: the MJPEG stream is smooth at 30 FPS regardless of how long
    each inference pass takes.  Between inference passes the detections
    "stick" — boxes remain visible on the live scene until YOLO updates them.

    The HUD now shows "AI: X FPS (inference)" which is the honest
    throughput of the YOLO engine, separate from stream delivery speed.
    """
    global global_frame
    interval = 1.0 / STREAM_FPS

    while True:
        t0 = time.time()

        # ── 1. Grab latest raw frame ──────────────────────────────
        with raw_lock:
            src = raw_frame
        if src is None:
            time.sleep(interval)
            continue
        frame = src.copy()          # stable local copy for this compositing pass

        # ── 2. Overlay last-known YOLO detections ─────────────────
        with boxes_lock:
            boxes    = list(last_boxes)
            status   = last_status
            inf_fps  = last_inf_fps

        for det in boxes:
            x1, y1, x2, y2 = det['bbox']
            color = COLOR_MAP.get(det['threat_level'], (255, 255, 255))
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{det['label'].upper()} {det['confidence']:.2f}",
                        (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # ── 3. HUD overlay ────────────────────────────────────────
        with tel_lock:
            dist = latest_distance
            spd  = latest_speed

        cv2.rectangle(frame, (0, 0), (220, 100), (0, 0, 0), -1)
        cv2.putText(frame, f"AI: {inf_fps:.1f} FPS (inference)",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 160, 160), 1)
        state_color = (0, 0, 255) if status == "THREAT_DETECTED" else (0, 255, 0)
        cv2.putText(frame, f"STATE: {status}",
                    (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.6, state_color, 2)
        d_str = f"{dist}m" if dist is not None else "--"
        s_str = f"{spd}km/h" if spd is not None else "--"
        cv2.putText(frame, f"D:{d_str}  V:{s_str}",
                    (10, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # ── 4. Hand off to Flask ──────────────────────────────────
        with frame_lock:
            global_frame = frame

        # Pace to target stream FPS (account for compositing time)
        elapsed = time.time() - t0
        remaining = interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

# ==========================================
# 5. FLASK WEB SERVER
# ==========================================
app = Flask(__name__)

def generate_frames():
    """Serve global_frame as an MJPEG stream.  Lock held only for the
    reference grab; encoding happens outside the lock."""
    while True:
        with frame_lock:
            frame = global_frame
        if frame is None:
            time.sleep(0.033)
            continue
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.033)           # cap HTTP push to ~30 FPS

@app.route('/')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ==========================================
# 6. AI & MQTT NODE
# ==========================================
class AirspaceSurveillanceNode:
    def __init__(self):
        print("🚀 Initializing Edge-AI Airspace Surveillance System...")

        # ── MQTT ──────────────────────────────────────────────────
        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="Pi_Node_1")
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_telemetry
        self.last_alert = None
        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            print(f"📡 MQTT connecting to {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            print(f"❌ MQTT connection failed: {e}")

        # ── YOLO ──────────────────────────────────────────────────
        try:
            self.model = YOLO(MODEL_NAME, task='detect')
            print(f"✅ YOLO model '{MODEL_NAME}' loaded.")
        except Exception as e:
            print(f"❌ Failed to load YOLO model: {e}")
            exit(1)

        # ── Camera ────────────────────────────────────────────────
        self.cap = cv2.VideoCapture(CAMERA_PATH, cv2.CAP_V4L2)
        # MJPG: compresses on-chip → ~10× less USB bandwidth than YUYV
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # always dequeue the newest frame
        if not self.cap.isOpened():
            print("❌ Cannot open camera.")
            exit(1)
        print(f"📷 Camera: {int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×"
              f"{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ "
              f"{int(self.cap.get(cv2.CAP_PROP_FPS))} FPS  "
              f"(FOURCC: {int(self.cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4,'little').decode()})")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(MQTT_TOPIC_TELEMETRY)
        print(f"📡 Subscribed to {MQTT_TOPIC_TELEMETRY}")

    def on_telemetry(self, client, userdata, msg):
        global latest_distance, latest_speed
        try:
            data = json.loads(msg.payload.decode())
            with tel_lock:
                latest_distance = round(float(data.get("distance_m", 0.0)), 2)
                latest_speed    = round(float(data.get("speed_mps", 0.0)) * 3.6, 1)
        except Exception as e:
            print(f"⚠️ Bad telemetry payload: {e}")

    def inference_loop(self):
        """
        Runs YOLO as fast as the hardware allows and updates last_boxes.
        Does NOT touch global_frame — that's entirely stream_loop's job.

        After re-exporting at imgsz=320, expect ~2-3 FPS here.
        The stream will remain smooth at 30 FPS regardless.
        """
        global last_boxes, last_status, last_inf_fps
        print("🧠 Inference loop running...")

        while True:
            # Grab the latest raw frame
            with raw_lock:
                src = raw_frame
            if src is None:
                time.sleep(0.01)
                continue

            frame = src.copy()
            t0 = time.time()

            results = self.model(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)

            # ── Parse detections ──────────────────────────────────
            boxes          = []
            detections_list = []
            hazard_count   = 0
            safe_count     = 0

            for box in results[0].boxes:
                label = self.model.names[int(box.cls[0])]
                conf  = round(float(box.conf[0].item()), 2)
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].cpu().numpy()]

                if label in HAZARD_CLASSES:
                    threat_level = 'HAZARDOUS'; hazard_count += 1
                elif label in SAFE_CLASSES:
                    threat_level = 'SAFE';      safe_count   += 1
                else:
                    threat_level = 'HAZARDOUS'; hazard_count += 1

                boxes.append({'bbox': (x1, y1, x2, y2), 'label': label,
                              'threat_level': threat_level, 'confidence': conf})
                detections_list.append({'object_type': label,
                                        'threat_level': threat_level,
                                        'confidence': conf})

            status  = "CLEAR" if hazard_count == 0 else "THREAT_DETECTED"
            inf_fps = 1.0 / max(time.time() - t0, 1e-6)

            # ── Push results to stream_loop ───────────────────────
            with boxes_lock:
                last_boxes   = boxes
                last_status  = status
                last_inf_fps = inf_fps

            # ── Build and publish MQTT payload ────────────────────
            with tel_lock:
                dist = latest_distance
                spd  = latest_speed

            payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "status": status,
                "summary": {
                    "total_objects": len(boxes),
                    "safe_count":    safe_count,
                    "hazard_count":  hazard_count,
                },
                "detections": detections_list,
            }
            if dist is not None: payload["distance"] = dist
            if spd  is not None: payload["speed"]    = spd

            self.mqtt_client.publish(MQTT_TOPIC_STATE, json.dumps(payload), qos=0)

            alert_state = "HAZARDOUS" if status == "THREAT_DETECTED" else "CLEAR"
            if alert_state != self.last_alert:
                self.mqtt_client.publish(MQTT_TOPIC_ALERT, alert_state, qos=1)
                self.last_alert = alert_state
                print(f"🔔 Alert → ESP32: {alert_state}")


# ==========================================
# 7. ENTRY POINT
# ==========================================
if __name__ == '__main__':
    # 1. Flask streaming server
    threading.Thread(target=run_flask, daemon=True).start()

    # 2. Open camera, load model, connect MQTT
    node = AirspaceSurveillanceNode()

    # 3. Camera capture thread  — drains V4L2 buffer at camera rate
    threading.Thread(target=capture_loop, args=(node.cap,), daemon=True).start()

    # 4. Stream compositing thread — overlays boxes on raw frames at 30 FPS
    threading.Thread(target=stream_loop, daemon=True).start()

    # 5. Inference loop in main thread — YOLO runs as fast as hardware allows
    node.inference_loop()