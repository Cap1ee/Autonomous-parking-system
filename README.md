# KDU Automated Smart Parking System

An automated parking management system for the General Sir John Kotelawala Defence University (KDU) campus. It combines computer vision and embedded hardware to read vehicle number plates at the gate, control entry and exit, and track slot occupancy in real time across campus parking zones.

## Features

- **Automatic Number Plate Recognition (ANPR):** YOLO v11 locates the plate and EasyOCR reads the text, running on a Raspberry Pi 4 with a Pi Camera v2.
- **Automated gate control:** a servo-driven barrier (RPi.GPIO, 50 Hz PWM) opens and closes based on recognition results.
- **Live slot detection:** IR and ultrasonic (HC-SR04) sensors report occupancy per slot, with one ESP32 handling the sensors in each zone.
- **Web dashboard:** a Flask app showing a real-time slot grid, entry log, and live MJPEG camera feed.
- **On-site display:** a 20x4 I2C LCD shows slot availability and gate status.
- **Zone-based management:** supports multiple campus zones (Law, FOC, Medicine, Computing, Non-Academic).

## System Architecture

```
 Pi Camera v2 --> Raspberry Pi 4 (YOLO v11 + EasyOCR) --> Servo gate
                         |
                         +--> SQLite (entry log, slot state) <--> Flask dashboard
                         |
 IR / HC-SR04 sensors --> ESP32 (per zone) --> Raspberry Pi 4
                         |
                         +--> 20x4 I2C LCD
```

## Tech Stack

| Area | Tools |
|------|-------|
| Computer vision | YOLO v11, EasyOCR, OpenCV |
| Backend / web | Python, Flask, SQLite |
| Embedded | Raspberry Pi 4, ESP32 (Arduino Core v3), RPi.GPIO |
| Sensors / actuators | HC-SR04, IR sensors, servo motor, PCF8574 I2C LCD |
| Simulation | Wokwi |

## Hardware

- Raspberry Pi 4
- ESP32 (one per zone)
- Raspberry Pi Camera v2 (CSI)
- HC-SR04 ultrasonic sensors and IR sensors
- Servo motor (gate barrier)
- 20x4 I2C LCD (PCF8574, address `0x27`)
- Breadboard power supply, LEDs

## Project Structure

```
.
├── anpr/          # YOLO v11 detection + EasyOCR recognition
├── dashboard/     # Flask web app (slot grid, logs, live feed)
├── esp32/         # Arduino sketches for slot sensing
├── gate/          # Servo gate control
├── docs/          # Wiring diagrams and documentation
└── README.md
```

> Adjust folder names to match your repository.

## Getting Started

### Prerequisites

- Raspberry Pi 4 with Raspberry Pi OS and the camera enabled
- Python 3.9+
- Arduino IDE with ESP32 Arduino Core v3

### Installation

```bash
git clone https://github.com/<your-username>/kdu-smartpark-dashboard.git
cd kdu-smartpark-dashboard
pip install -r requirements.txt
```

### Run

```bash
# Start the dashboard and ANPR pipeline
python app.py
```

Then open `http://<raspberry-pi-ip>:5000` in a browser on the same network.

Flash the sketches in `esp32/` to each zone controller using the Arduino IDE.

## Project Status

Implementation and integration are underway, with ANPR implemented and evaluated. Full system integration testing across all zones is in progress, using a 3x3 ft prototype board of the car park layout.


## License

Add a license of your choice (e.g. MIT) or state that this project is for academic use.
