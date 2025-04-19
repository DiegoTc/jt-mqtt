#!/bin/bash

echo "Starting Mosquitto MQTT broker for PetTracker testing..."

# Check if Mosquitto is already running
if pgrep mosquitto > /dev/null; then
    echo "⚠️ Mosquitto broker is already running"
    exit 0
fi

# Create a minimal Mosquitto config directly
echo "listener 1883 0.0.0.0" > mosquitto.conf
echo "allow_anonymous true" >> mosquitto.conf
echo "connection_messages true" >> mosquitto.conf
echo "log_type none" >> mosquitto.conf
echo "persistence false" >> mosquitto.conf
echo "max_queued_messages 100" >> mosquitto.conf
echo "max_inflight_messages 20" >> mosquitto.conf
echo "message_size_limit 10240" >> mosquitto.conf
echo "listener 9001 0.0.0.0" >> mosquitto.conf
echo "protocol websockets" >> mosquitto.conf

echo "📝 Updated mosquitto.conf for Replit environment"

# Start Mosquitto with our configuration in the background, redirecting output to /dev/null
mosquitto -c mosquitto.conf > /dev/null 2>&1 &

# Store PID for later reference
MQTT_PID=$!
echo $MQTT_PID > /dev/null

# Check if process started successfully
sleep 1
if ps -p $MQTT_PID > /dev/null; then
    echo "✅ Mosquitto MQTT broker started successfully (PID: $MQTT_PID)"
else
    echo "❌ Failed to start Mosquitto broker."
    exit 1
fi