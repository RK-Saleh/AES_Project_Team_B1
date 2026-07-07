from flask import Flask, Response
import cv2

app = Flask(__name__)

# Initialize the webcam
cap = cv2.VideoCapture(0)

def generate_frames():
    while True:
        # Read the camera frame
        success, frame = cap.read()
        if not success:
            break
        else:
            # Encode the frame in JPEG format
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()

            # Yield the frame in byte format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def video_feed():
    # Return the response generated along with the specific media type (mime type)
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    # Host on 0.0.0.0 to make it accessible to other devices on the network
    app.run(host='0.0.0.0', port=5000)