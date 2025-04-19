#!/usr/bin/env python3
"""
MQTT Monitor - A simple tool to subscribe to MQTT topics and display messages
"""
import paho.mqtt.client as mqtt
import json
import time
import argparse
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mqtt-monitor')

def on_connect(client, userdata, flags, rc):
    """Callback when client connects to the broker"""
    if rc == 0:
        logger.info(f"Connected to MQTT broker with result code {rc}")
        
        # Subscribe to topics based on provided arguments
        topics = userdata.get('topics', ['#'])  # Default to all topics
        for topic in topics:
            logger.info(f"Subscribing to topic: {topic}")
            client.subscribe(topic, qos=1)
    else:
        logger.error(f"Failed to connect to MQTT broker with result code {rc}")

def on_disconnect(client, userdata, rc):
    """Callback when client disconnects from the broker"""
    if rc != 0:
        logger.warning(f"Unexpected disconnection, result code: {rc}")
    else:
        logger.info("Disconnected from MQTT broker")

def on_message(client, userdata, msg):
    """Callback when a message is received"""
    try:
        # Try to parse as JSON
        payload = json.loads(msg.payload.decode())
        pretty_payload = json.dumps(payload, indent=2)
        logger.info(f"Received message on topic {msg.topic}:\n{pretty_payload}")
    except:
        # If not JSON, display as string
        logger.info(f"Received message on topic {msg.topic}: {msg.payload.decode()}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='MQTT Monitor')
    parser.add_argument('-b', '--broker', default='broker.hivemq.com', 
                        help='MQTT broker address (default: broker.hivemq.com)')
    parser.add_argument('-p', '--port', type=int, default=1883, 
                        help='MQTT broker port (default: 1883)')
    parser.add_argument('-t', '--topics', nargs='+', default=['pettracker/#'], 
                        help='MQTT topics to subscribe to (default: pettracker/#)')
    parser.add_argument('-v', '--verbose', action='store_true', 
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Additional topic suggestions
    if len(args.topics) == 1 and args.topics[0] == 'pettracker/#':
        logger.info("Monitoring all pettracker topics. You may want to try specific topics such as:")
        logger.info("  - pettracker/123456/location")
        logger.info("  - pettracker/123456/heartbeat")
        logger.info("  - pettracker/123456/status")
    
    # Create MQTT client with topics as userdata
    client = mqtt.Client(client_id=f"mqtt-monitor-{int(time.time())}", userdata={'topics': args.topics})
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    
    try:
        # Connect to MQTT broker
        logger.info(f"Connecting to MQTT broker at {args.broker}:{args.port}...")
        client.connect(args.broker, args.port, keepalive=60)
        
        # Loop forever
        logger.info("Starting MQTT monitoring. Press Ctrl+C to exit.")
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        client.disconnect()

if __name__ == '__main__':
    main()