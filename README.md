# JT/T 808-2013 GPS Tracker Simulator with MQTT Converter

This project provides a complete implementation of a JT/T 808-2013 GPS tracking simulator and a converter that translates the protocol messages to MQTT format.

## Features

### GPS Tracking Simulator
- Implementation of JT/T 808-2013 protocol
- Simulates GPS device movement
- Supports terminal registration, authentication, heartbeat, and location reporting
- Configurable parameters (device ID, coordinates, movement, etc.)
- Support for batch location reports

### MQTT Converter
- Listens for JT/T 808 messages on a TCP socket
- Decodes and parses the protocol messages
- Converts messages to JSON format
- Publishes to appropriate MQTT topics
- Handles multiple client connections

## Installation

### Prerequisites
- Python 3.6 or higher
- Required packages: paho-mqtt

```bash
pip install paho-mqtt
