#include <SPI.h>
#include <WiFiNINA.h>
#include <ArduinoMqttClient.h>
#include <NewPing.h>

// ==========================================
// 1. CONFIGURATION & CREDENTIALS
// ==========================================
const char ssid[] = "Pixel21";          // <-- CHANGE THIS
const char pass[] = "12345678a";        // <-- CHANGE THIS

// IP address of Node 1 (Raspberry Pi) running Mosquitto / Node-RED
const char broker[] = "10.40.147.160";   // <-- CHANGE THIS
int        port     = 1883;
const char topic[]  = "airspace/node2/telemetry";

// ==========================================
// 2. HARDWARE PINS & CONSTANTS
// ==========================================
#define TRIGGER_PIN  9
#define ECHO_PIN     10
#define MAX_DISTANCE 100 // 50cm limit for bench testing

NewPing sonar(TRIGGER_PIN, ECHO_PIN, MAX_DISTANCE);
WiFiClient wifiClient;
MqttClient mqttClient(wifiClient);

// ==========================================
// 3. TIMING & KINEMATICS VARIABLES
// ==========================================
unsigned long lastSensorReadTime = 0;
unsigned long lastPublishTime = 0;
const int sensorInterval = 50;     // Fast loop: Physics (50ms)
const int publishInterval = 533;   // Slow loop: Network & UI (533ms)

const int numReadings = 5;
int readings[numReadings];
float smoothedDistance_cm = 0;

float previousDistance_cm = 0;
unsigned long lastSpeedTime = 0;   // Replaces previousTime for wider window
float speed_mps = 0;
bool firstReading = true;
int currentRaw_cm = 0;

void setup() {
  Serial.begin(115200);
  while (!Serial); 
  delay(1000);

  Serial.println("\n--- Edge-AI Node 2 Boot Sequence ---");

  // Initialize reading array with zeros
  for (int i = 0; i < numReadings; i++) {
    readings[i] = 0;
  }

  connectWiFi();
  connectMQTT();
}

void loop() {
  // 1. Keep MQTT Alive (Non-blocking)
  mqttClient.poll();

  // 2. Auto-Reconnect Logic
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqttClient.connected()) connectMQTT();

  unsigned long currentMillis = millis();

  // 3. DATA ACQUISITION & PUBLISH LOOP
  if (currentMillis - lastSensorReadTime >= sensorInterval) {
    lastSensorReadTime = currentMillis;
    currentRaw_cm = sonar.ping_cm(); 
    
    // IF OBJECT IS IN RANGE
    if (currentRaw_cm > 0 && currentRaw_cm <= MAX_DISTANCE) {
      updateDistanceFilter(currentRaw_cm);
      calculateSpeed(currentMillis);
      
      // Throttle network publishing to preserve bandwidth
      if (currentMillis - lastPublishTime >= publishInterval) {
        lastPublishTime = currentMillis;
        publishTelemetry();
      }
    } 
    // IF OBJECT LEAVES RANGE
    else {
      if (!firstReading) {
        // Reset kinematics for the next object that enters
        firstReading = true;
        speed_mps = 0.0;
        smoothedDistance_cm = 0.0;
        
        // Clear the array to prevent old data ghosting
        for (int i = 0; i < numReadings; i++) readings[i] = 0;
        
        // Publish ONE final telemetry packet to zero out the Pi/Dashboard
        publishTelemetry(); 
      }
    }
  }
}

// ==========================================
// ADVANCED SIGNAL PROCESSING
// ==========================================

void updateDistanceFilter(int newReading) {
  // 1. Shift old readings left (discard oldest)
  for (int i = 0; i < numReadings - 1; i++) {
    readings[i] = readings[i + 1];
  }
  // 2. Add new reading at the end
  readings[numReadings - 1] = newReading;

  // 3. Create a temporary array to sort
  int sorted[numReadings];
  for (int i = 0; i < numReadings; i++) {
    sorted[i] = readings[i];
  }

  // 4. Insertion Sort (Fast for small arrays)
  for (int i = 1; i < numReadings; i++) {
    int key = sorted[i];
    int j = i - 1;
    while (j >= 0 && sorted[j] > key) {
      sorted[j + 1] = sorted[j];
      j = j - 1;
    }
    sorted[j + 1] = key;
  }

  // 5. Pick the Median (the exact middle value) to eliminate noise
  smoothedDistance_cm = sorted[numReadings / 2];
}

void calculateSpeed(unsigned long currentTime) {
  if (firstReading) {
    previousDistance_cm = smoothedDistance_cm;
    lastSpeedTime = currentTime;
    speed_mps = 0.0;
    firstReading = false;
    return;
  }

  // Only calculate speed every 250ms for a stable, radar-like baseline
  unsigned long delta_t = currentTime - lastSpeedTime;
  
  if (delta_t >= 250) { 
    float delta_d = smoothedDistance_cm - previousDistance_cm;
    
    // Velocity in cm/ms is equivalent to m/s * 10
    float raw_velocity_mps = (delta_d / (float)delta_t) * 10.0; 

    // Apply a light Low-Pass Filter (EMA) to the speed: 
    // 60% new reading, 40% old reading (acts as software inertia)
    speed_mps = (0.6 * raw_velocity_mps) + (0.4 * speed_mps);

    // Save state for the next kinematic window
    previousDistance_cm = smoothedDistance_cm;
    lastSpeedTime = currentTime;
  }
}

// ==========================================
// NETWORK FUNCTIONS
// ==========================================

void publishTelemetry() {
  // Convert cm to meters
  float distance_m = smoothedDistance_cm / 100.0;

  // Build the JSON payload safely without snprintf float limitations
  String payload = "{\"node\":\"node2\",\"distance_m\":";
  payload += String(distance_m, 2);
  payload += ",\"speed_mps\":";
  payload += String(speed_mps, 2);
  payload += "}";

  // 1. Send to USB Serial safely
  Serial.print("Publishing: ");
  Serial.println(payload);
  Serial.flush(); // Lock the processor until USB is 100% finished

  // 2. Send to Wi-Fi safely
  mqttClient.beginMessage(topic);
  mqttClient.print(payload);
  mqttClient.endMessage();
  
  // 3. Give the Wi-Fi radio a tiny break before the next sonar ping
  delay(10); 
}

void connectWiFi() {
  Serial.print("Connecting to Wi-Fi: ");
  Serial.println(ssid);
  
  WiFi.begin(ssid, pass);
  
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(1000); 
  }
  Serial.println("\nWi-Fi connected!");
}

void connectMQTT() {
  Serial.print("Connecting to MQTT broker: ");
  Serial.println(broker);
  while (!mqttClient.connect(broker, port)) {
    Serial.print("MQTT connection failed! Error: ");
    Serial.println(mqttClient.connectError());
    delay(1000); 
  }
  Serial.println("MQTT connected!");
}