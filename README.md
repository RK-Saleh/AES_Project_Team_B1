# Edge-AI Airspace Surveillance System 

## Overview
This project is a **distributed IoT early warning system** designed for airspace surveillance. It integrates edge AI computer vision, distance and speed tracking, and remote MQTT alerting to monitor, detect, and report on moving objects in real-time.

## Key Features
* **Edge AI Vision:** Utilizes a lightweight, optimized YOLOv8 model (NCNN) to perform real-time object detection directly on edge hardware.
* **Telemetry Tracking:** Hardware-level sensor integration to calculate object distance and velocity.
* **Distributed Alerting:** Uses the MQTT protocol to send instantaneous, remote early warnings across different nodes.
* **IoT Ecosystem:** Seamlessly links vision processing software with microcontrollers and a central dashboard.

## Hardware Components
* **Arduino UNO:** Handles localized sensor data acquisition for distance and speed measurements.
* **ESP32:** Manages network connectivity and acts as the MQTT communication hub.
* **Edge Vision Node:** Runs the Python-based AI detection scripts.

## Software & Tech Stack
* **Machine Learning:** YOLOv8, NCNN, Jupyter Notebooks.
* **Languages:** Python (Vision Processing), C++ / Arduino (Microcontroller Firmware).
* **Networking & UI:** MQTT protocol, Node-RED (for workflow routing and dashboarding).
* **System Architecture:** SysML for structured system modeling.

## Repository Structure
* 📂 **`YOLOv8_ncnn_model/`** - The compiled and optimized YOLO vision model for edge deployment.
* 📂 **`sysML/`** - System Modeling Language files and architecture diagrams.
* 📄 **`Arduino_UN0_REV2.ino`** - Firmware for the Arduino handling speed/distance logic.
* 📄 **`ESP32.ino`** - Firmware for the ESP32 handling MQTT communications.
* 📄 **`node1_vision_v2.py`** - Core Python script running the computer vision and detection logic.
* 📄 **`YOLO_Model.ipynb`** - Jupyter Notebook used for initial model training and evaluation.
* 📄 **`flows.json`** - Node-RED configuration file for the alerting dashboard.
* 📄 **`Final_Documentation...pdf`** - Comprehensive technical documentation for the system.
