#!/bin/bash

echo "Starting Mosquitto MQTT broker for PetTracker testing..."

# Create persistence directory if it doesn't exist
mkdir -p /tmp/mosquitto/

# Start Mosquitto with our configuration
mosquitto -c mosquitto.conf -v