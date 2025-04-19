#!/usr/bin/env python3
"""
Quick MQTT Test for PetTracker
Standalone script to test MQTT connection and publish/subscribe
"""
import paho.mqtt.client as mqtt
import json
import time
import random
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mqtt-test')

# Generate a unique client ID
client_id = f"pettracker-test-{random.randint(1000, 9999)}"

# HiveMQ broker settings
broker = "broker.hivemq.com"
port = 1883
test_topic = "pettracker/test"

def on_connect(client, userdata, flags, rc):
    """Callback when connected to broker"""
    if rc == 0:
        logger.info(f"Connected to MQTT broker: {broker}:{port}")
        logger.info(f"Client ID: {client_id}")
        
        # Subscribe to test topic
        client.subscribe(test_topic)
        logger.info(f"Subscribed to: {test_topic}")
        
        # Publish test message
        test_payload = {
            "device_id": "test_device",
            "timestamp": datetime.now().isoformat() + 'Z',
            "status": "online",
            "test": True
        }
        client.publish(test_topic, json.dumps(test_payload), qos=1)
        logger.info(f"Published test message to: {test_topic}")
    else:
        logger.error(f"Failed to connect to MQTT broker. Result code: {rc}")

def on_message(client, userdata, msg):
    """Callback when message received"""
    try:
        logger.info(f"Received message on topic: {msg.topic}")
        payload = json.loads(msg.payload.decode())
        logger.info(f"Message payload: {json.dumps(payload, indent=2)}")
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        logger.info(f"Raw message: {msg.payload.decode()}")

def on_disconnect(client, userdata, rc):
    """Callback when disconnected from broker"""
    if rc != 0:
        logger.warning(f"Unexpected disconnection. Result code: {rc}")
    else:
        logger.info("Disconnected from MQTT broker")

def main():
    """Main function"""
    # Create MQTT client
    client = mqtt.Client(client_id=client_id)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    
    try:
        # Connect to broker
        logger.info(f"Connecting to MQTT broker at {broker}:{port}...")
        client.connect(broker, port, keepalive=60)
        
        # Start network loop and wait
        client.loop_start()
        
        # Publish messages periodically
        for i in range(5):
            time.sleep(2)
            test_payload = {
                "device_id": "test_device",
                "timestamp": datetime.now().isoformat() + 'Z',
                "message_number": i + 1,
                "random_value": random.randint(1, 100)
            }
            client.publish(test_topic, json.dumps(test_payload), qos=1)
            logger.info(f"Published message #{i+1}")
        
        # Wait a bit to receive all messages
        time.sleep(2)
        
        # Disconnect
        client.loop_stop()
        client.disconnect()
        logger.info("Test completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        client.disconnect()
    except Exception as e:
        logger.error(f"Error: {e}")
        
if __name__ == "__main__":
    main()