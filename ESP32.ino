#include <WiFi.h>
#include <PubSubClient.h>

// ── WiFi credentials ──────────────────────────────────────
const char* ssid        = "Pixel21";
const char* password    = "12345678a";

// ── Raspberry Pi MQTT Broker ──────────────────────────────
const char* mqtt_server = "10.40.147.160";   // Pi's IP
const int   mqtt_port   = 1883;
const char* alert_topic = "airspace/alert"; 

// ── Buzzer Pin ────────────────────────────────────────────
const int BUZZER_PIN = 5;

// ── Non-Blocking State Variables (ACTIVE-HIGH LOGIC) ──────
bool isAlarmActive = false;
unsigned long lastBuzzerToggle = 0;
bool buzzerState = LOW; // LOW = OFF, HIGH = ON

WiFiClient   espClient;
PubSubClient client(espClient);

// ── Connect to WiFi ───────────────────────────────────────
void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected! IP: " + WiFi.localIP().toString());
}

// ── Called automatically when MQTT message arrives ────────
void onMessageReceived(char* topic, byte* payload, unsigned int length) {
  String message = "";
  for (int i = 0; i < length; i++) message += (char)payload[i];

  Serial.println("----------------------------");
  Serial.println("Topic  : " + String(topic));
  Serial.println("Message: " + message);

  if (message == "HAZARDOUS" || message == "ALERT") {
    Serial.println("⚠️ THREAT DETECTED! Alarm Armed");
    isAlarmActive = true;
  } else if (message == "SAFE" || message == "CLEAR") {
    Serial.println("✅ All Clear. Alarm Disarmed");
    isAlarmActive = false;
    
    // CRITICAL FIX: Force the pin LOW to turn the buzzer OFF
    buzzerState = LOW; 
    digitalWrite(BUZZER_PIN, buzzerState);   
  } else {
    Serial.println("Unknown message received");
  }
}

// ── Connect to MQTT Broker (Pi) ───────────────────────────
void connectMQTT() {
  while (!client.connected()) {
    Serial.print("Connecting to MQTT Broker...");
    String clientId = "ESP32_Node3_" + String(random(0xffff), HEX);

    if (client.connect(clientId.c_str())) {
      Serial.println("Connected!");
      client.subscribe(alert_topic);
      Serial.println("Subscribed to topic: " + String(alert_topic));
    } else {
      Serial.print("Failed. State=");
      Serial.println(client.state());
      Serial.println("Retrying in 3 seconds...");
      delay(3000);
    }
  }
}

// ── Setup ─────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  
  // CRITICAL FIX: Ensure buzzer is OFF at startup by sending LOW
  digitalWrite(BUZZER_PIN, LOW);   

  connectWiFi();

  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(onMessageReceived);

  connectMQTT();
}

// ── Loop ──────────────────────────────────────────────────
void loop() {
  if (!client.connected()) {
    connectMQTT();
  }
  
  client.loop(); // Must run rapidly without being blocked by delay()

  // ── Non-Blocking Buzzer Logic (ACTIVE-HIGH FIX) ─────────
  if (isAlarmActive) {
    unsigned long currentMillis = millis();
    
    // If buzzer is ON (HIGH), wait 500ms before turning OFF (LOW)
    if (buzzerState == HIGH && (currentMillis - lastBuzzerToggle >= 500)) {
      buzzerState = LOW;
      digitalWrite(BUZZER_PIN, buzzerState);
      lastBuzzerToggle = currentMillis;
    }
    // If buzzer is OFF (LOW), wait 300ms before turning ON (HIGH)
    else if (buzzerState == LOW && (currentMillis - lastBuzzerToggle >= 300)) {
      buzzerState = HIGH;
      digitalWrite(BUZZER_PIN, buzzerState);
      lastBuzzerToggle = currentMillis;
    }
  }
}