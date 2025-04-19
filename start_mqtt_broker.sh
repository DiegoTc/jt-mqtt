#!/bin/bash

echo "Starting Mosquitto MQTT broker for PetTracker testing..."

# Check if Mosquitto is already running
if pgrep mosquitto > /dev/null; then
    echo "⚠️ Mosquitto broker is already running"
    exit 0
fi

# Ensure mosquitto.conf has persistence disabled to avoid disk quota issues
if ! grep -q "persistence false" mosquitto.conf; then
    echo "⚠️ Adding 'persistence false' to mosquitto.conf"
    echo "persistence false" >> mosquitto.conf
fi

# Start Mosquitto with our configuration in the background
nohup mosquitto -c mosquitto.conf -v > mosquitto.log 2>&1 &

# Store PID for later reference
MQTT_PID=$!
echo $MQTT_PID > mosquitto.pid

# Check if process started successfully
sleep 1
if ps -p $MQTT_PID > /dev/null; then
    echo "✅ Mosquitto MQTT broker started successfully (PID: $MQTT_PID)"
    echo "Logs being written to mosquitto.log"
else
    echo "❌ Failed to start Mosquitto broker. Check mosquitto.log for details."
    exit 1
fi