#!/usr/bin/env python3
"""
Simple MQTT test script that both subscribes and publishes to a topic
"""
import time
import paho.mqtt.client as mqtt
import json
import logging
import uuid
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - mqtt-test - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mqtt-test")

# Generate unique client IDs
sub_client_id = f"mqtt-test-sub-{uuid.uuid4().hex[:8]}"
pub_client_id = f"mqtt-test-pub-{uuid.uuid4().hex[:8]}"

# MQTT client for subscribing
sub_client = mqtt.Client(client_id=sub_client_id, clean_session=True)
# MQTT client for publishing
pub_client = mqtt.Client(client_id=pub_client_id, clean_session=True)

# Tracking whether we've received the test message
message_received = False

# Define a fixed test topic - using a fixed one for simplicity
test_topic = "test/pettracker/mqtt_test"

# Lock for thread safety
topic_lock = threading.Lock()

def on_connect(client, userdata, flags, rc):
    """Callback when client connects to the broker"""
    if rc == 0:
        logger.info(f"Connected to MQTT broker with result code {rc}, client_id: {client._client_id.decode()}")
        # If this is the subscriber client, subscribe to the test topic
        if client._client_id.startswith(b"mqtt-test-sub"):
            client.subscribe(test_topic, qos=1)
            logger.info(f"Subscribed to topic: {test_topic} with QoS 1")
            
            # Subscribe to multiple wildcard topics to see all messages
            wildcard_topics = ["pettracker/#", "+/#", "#"]
            for topic in wildcard_topics:
                client.subscribe(topic, qos=1)
                logger.info(f"Also subscribed to wildcard topic: {topic}")
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
    logger.info(f"Message received on topic {msg.topic} with QoS {msg.qos}")
    
    try:
        payload = msg.payload.decode()
        logger.info(f"Raw payload: {payload}")
        
        try:
            json_payload = json.loads(payload)
            logger.info(f"Parsed JSON: {json_payload}")
            message_received = True
        except json.JSONDecodeError:
            logger.warning(f"Received non-JSON message: {payload}")
            # Still count as received for wildcard topics
            if msg.topic == test_topic:
                message_received = True
    except Exception as e:
        logger.error(f"Error processing message: {e}")

def on_subscribe(client, userdata, mid, granted_qos):
    """Callback when subscription is made"""
    logger.info(f"Subscription confirmed. Message ID: {mid}, Granted QoS: {granted_qos}")

def on_publish(client, userdata, mid):
    """Callback when a message is published"""
    logger.info(f"Message published with ID: {mid}")

def run_test():
    """Run the MQTT test"""
    global message_received

    # Set up callbacks for subscriber
    sub_client.on_connect = on_connect
    sub_client.on_disconnect = on_disconnect
    sub_client.on_message = on_message
    sub_client.on_subscribe = on_subscribe

    # Set up callbacks for publisher
    pub_client.on_connect = on_connect
    pub_client.on_disconnect = on_disconnect
    pub_client.on_publish = on_publish

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

        # Wait for subscriber to connect and subscribe
        time.sleep(3)
        
        # Use our fixed test topic
        # Publish test message
        test_message = {
            "timestamp": time.time(),
            "message": "Hello from MQTT test",
            "client_id": pub_client_id
        }
        logger.info(f"Publishing message to {test_topic}: {test_message}")
        result = pub_client.publish(test_topic, json.dumps(test_message), qos=1)
        
        # Check publish result
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error(f"Failed to publish message: {mqtt.error_string(result.rc)}")
        else:
            logger.info("Message published successfully")

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