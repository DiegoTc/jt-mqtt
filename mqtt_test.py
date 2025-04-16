#!/usr/bin/env python3
"""
Simple MQTT test script that both subscribes and publishes to a topic
"""
import time
import paho.mqtt.client as mqtt
import json
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - mqtt-test - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mqtt-test")

# MQTT client for subscribing
sub_client = mqtt.Client(client_id="mqtt-test-sub", clean_session=True)
# MQTT client for publishing
pub_client = mqtt.Client(client_id="mqtt-test-pub", clean_session=True)

# Tracking whether we've received the test message
message_received = False

def on_connect(client, userdata, flags, rc):
    """Callback when client connects to the broker"""
    if rc == 0:
        logger.info(f"Connected to MQTT broker with result code {rc}")
        if client._client_id == b"mqtt-test-sub":
            # Use a unique topic with timestamp to avoid conflicts
            import time
            timestamp = int(time.time())
            topic = f"test/pettracker/{timestamp}"
            client.subscribe(topic)
            logger.info(f"Subscribed to topic: {topic}")
            # Store the topic in userdata for the publisher to use
            client._userdata = topic
    else:
        logger.error(f"Failed to connect to MQTT broker with result code {rc}")

def on_disconnect(client, userdata, rc):
    """Callback when client disconnects from the broker"""
    if rc != 0:
        logger.warning(f"Unexpected disconnection with result code {rc}")
    else:
        logger.info("Disconnected from broker")

def on_message(client, userdata, msg):
    """Callback when a message is received"""
    global message_received
    try:
        payload = json.loads(msg.payload.decode())
        logger.info(f"Received message on {msg.topic}: {payload}")
        message_received = True
    except json.JSONDecodeError:
        logger.warning(f"Received non-JSON message on {msg.topic}: {msg.payload.decode()}")
        message_received = True

def run_test():
    """Run the MQTT test"""
    global message_received

    # Set up callbacks for subscriber
    sub_client.on_connect = on_connect
    sub_client.on_disconnect = on_disconnect
    sub_client.on_message = on_message

    # Set up callbacks for publisher
    pub_client.on_connect = on_connect
    pub_client.on_disconnect = on_disconnect

    # Connect to broker
    try:
        # Connect to HiveMQ's public broker instead of localhost
        broker_address = "broker.hivemq.com"
        broker_port = 1883
        
        logger.info(f"Connecting subscriber to MQTT broker at {broker_address}:{broker_port}...")
        sub_client.connect(broker_address, broker_port, 60)
        sub_client.loop_start()

        logger.info(f"Connecting publisher to MQTT broker at {broker_address}:{broker_port}...")
        pub_client.connect(broker_address, broker_port, 60)
        pub_client.loop_start()

        # Wait for subscriber to connect
        time.sleep(2)

        # Wait for the subscriber to create the topic and share it
        wait_count = 0
        while hasattr(sub_client, '_userdata') is False or sub_client._userdata is None:
            time.sleep(0.5)
            wait_count += 1
            if wait_count > 10:  # 5 seconds max
                logger.error("Timed out waiting for subscriber to create topic")
                break
        
        # Get the topic from the subscriber
        topic = getattr(sub_client, '_userdata', 'test/message')
        
        # Publish test message
        test_message = {"timestamp": time.time(), "message": "Hello from MQTT test"}
        logger.info(f"Publishing message to {topic}: {test_message}")
        pub_client.publish(topic, json.dumps(test_message), qos=1)

        # Wait for the message to be received
        timeout = 30  # Longer timeout for public broker
        start_time = time.time()
        while not message_received and (time.time() - start_time) < timeout:
            time.sleep(0.5)
            logger.info(f"Waiting for message... ({int(time.time() - start_time)}s elapsed)")

        if message_received:
            logger.info("Test successful: Message was published and received")
        else:
            logger.error(f"Test failed: Message was not received within {timeout} seconds")

    except Exception as e:
        logger.error(f"Error during MQTT test: {e}")
    finally:
        # Clean up
        sub_client.loop_stop()
        pub_client.loop_stop()
        sub_client.disconnect()
        pub_client.disconnect()

if __name__ == "__main__":
    run_test()