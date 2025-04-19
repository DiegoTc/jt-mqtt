#!/bin/bash

echo "Starting Mosquitto MQTT broker for PetTracker testing..."

# Start Mosquitto with our configuration (persistence disabled in config)
mosquitto -c mosquitto.conf -v