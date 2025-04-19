#!/usr/bin/env python3
"""
PetTracker GPS Simulator

An asyncio-based simulator for generating realistic GPS tracking data
for pet tracking devices and publishing them to MQTT.
"""
import asyncio
import logging
import math
import random
import time
import json
from datetime import datetime
import paho.mqtt.client as mqtt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('pettracker-simulator')

class GPSTrackingSimulator:
    """
    GPS Tracking Simulator with asyncio architecture
    
    Simulates a GPS tracking device sending data to MQTT broker
    """
    def __init__(self, config):
        """
        Initialize the simulator with configuration
        
        Args:
            config: Configuration dictionary
        """
        # MQTT Configuration
        mqtt_config = config.get('mqtt', {})
        if not mqtt_config:
            logger.warning("No MQTT configuration found, using defaults")
            mqtt_config = {
                "broker_url": "test.mosquitto.org",
                "broker_port": 1883
            }
            
        self.mqtt_broker = mqtt_config.get('broker_url', 'test.mosquitto.org')
        self.mqtt_port = mqtt_config.get('broker_port', 1883)
        # Ensure client ID is unique by adding timestamp and random suffix
        client_id_base = mqtt_config.get('client_id', "pettracker_simulator")
        self.mqtt_client_id = f"{client_id_base}_{int(time.time())}_{random.randint(1000, 9999)}"
        self.mqtt_username = mqtt_config.get('username', '')
        self.mqtt_password = mqtt_config.get('password', '')
        self.mqtt_use_tls = mqtt_config.get('use_tls', False)
        
        # Device Configuration
        device_config = config.get('device', {})
        if not device_config:
            logger.warning("No device configuration found, using defaults")
            device_config = {
                "device_id": "123456",
                "start_lat": 14.072275,
                "start_lon": -87.192136
            }
            
        self.device_id = device_config.get('device_id', '123456')
        self.latitude = device_config.get('start_lat', 14.072275)
        self.longitude = device_config.get('start_lon', -87.192136)
        
        # Simulation Configuration
        sim_config = config.get('simulation', {})
        if not sim_config:
            logger.warning("No simulation configuration found, using defaults")
            sim_config = {
                "location_interval": 5,
                "heartbeat_interval": 30,
                "status_interval": 300,
                "movement_speed": 5,
                "direction_change_probability": 0.2,
                "movement_variation": 0.3
            }
            
        self.location_interval = sim_config.get('location_interval', 5)
        self.heartbeat_interval = sim_config.get('heartbeat_interval', 30)
        self.status_interval = sim_config.get('status_interval', 300)
        
        # Movement Parameters
        self.movement_speed = sim_config.get('movement_speed', 5)  # meters per second
        self.direction = random.uniform(0, 360)  # random initial direction
        self.direction_change_probability = sim_config.get('direction_change_probability', 0.2)
        self.movement_variation = sim_config.get('movement_variation', 0.3)
        
        # Runtime state
        self.mqtt_client = None
        self.running = False
        self.tasks = []
        
        logger.info(f"Initialized PetTracker Simulator for device {self.device_id}")
        logger.info(f"Will connect to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")
        logger.info(f"Location updates every {self.location_interval}s")
        logger.info(f"Heartbeat updates every {self.heartbeat_interval}s")
        logger.info(f"Status updates every {self.status_interval}s")
    
    async def start(self):
        """Start the simulator"""
        if self.running:
            logger.warning("Simulator is already running")
            return
        
        logger.info("Starting PetTracker simulator")
        self.running = True
        
        # Connect to MQTT broker
        await self._connect_mqtt()
        
        # Start the coroutines
        self.tasks = [
            asyncio.create_task(self._send_location_loop()),
            asyncio.create_task(self._send_heartbeat_loop()),
            asyncio.create_task(self._send_status_loop())
        ]
        
        logger.info("All simulator tasks started")
    
    async def stop(self):
        """Stop the simulator"""
        if not self.running:
            logger.warning("Simulator is not running")
            return
        
        logger.info("Stopping PetTracker simulator")
        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        
        # Wait for tasks to complete cancellation
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # Disconnect MQTT client
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()
            logger.info("Disconnected from MQTT broker")
        
        logger.info("Simulator stopped")
    
    async def _connect_mqtt(self):
        """Connect to the MQTT broker"""
        try:
            # Create a new client instance with a unique ID
            self.mqtt_client = mqtt.Client(client_id=self.mqtt_client_id)
            
            # Set up callbacks
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
            self.mqtt_client.on_publish = self._on_mqtt_publish
            
            # Set credentials if provided
            if self.mqtt_username and self.mqtt_password:
                self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)
            
            # Set TLS if required
            if self.mqtt_use_tls:
                self.mqtt_client.tls_set()
            
            # Connect
            logger.info(f"Connecting to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")
            self.mqtt_client.connect_async(self.mqtt_broker, self.mqtt_port, keepalive=60)
            
            # Start the MQTT client loop in a background thread
            self.mqtt_client.loop_start()
            
            # Wait for the connection to establish
            connection_timeout = 15  # seconds
            start_time = time.time()
            connected = False
            
            while time.time() - start_time < connection_timeout:
                if self.mqtt_client.is_connected():
                    connected = True
                    break
                await asyncio.sleep(0.5)
            
            if not connected:
                logger.error(f"Failed to connect to MQTT broker after {connection_timeout} seconds")
                self.mqtt_client.loop_stop()
                raise ConnectionError(f"Failed to connect to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")
            
            logger.info(f"Successfully connected to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting to MQTT broker: {e}")
            if hasattr(self, 'mqtt_client') and self.mqtt_client:
                try:
                    self.mqtt_client.loop_stop()
                except:
                    pass
            raise ConnectionError(f"Failed to connect to MQTT broker: {str(e)}")
    
    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """MQTT connect callback"""
        if rc == 0:
            logger.info("Successfully connected to MQTT broker")
        else:
            logger.error(f"Failed to connect to MQTT broker, return code: {rc}")
    
    def _on_mqtt_disconnect(self, client, userdata, rc):
        """MQTT disconnect callback"""
        if rc != 0:
            logger.warning(f"Unexpected disconnection from MQTT broker, return code: {rc}")
        else:
            logger.info("Disconnected from MQTT broker")
    
    def _on_mqtt_publish(self, client, userdata, mid):
        """MQTT publish callback"""
        logger.debug(f"Message published with ID: {mid}")
    
    async def _send_location_loop(self):
        """
        Send location updates every self.location_interval seconds
        """
        logger.info(f"Starting location update loop (every {self.location_interval}s)")
        
        while self.running:
            try:
                # Update location to simulate movement
                self._update_location()
                
                # Create location message
                message = {
                    "d": self.device_id,
                    "t": self._get_timestamp(),
                    "loc": {
                        "lat": round(self.latitude, 6),
                        "lon": round(self.longitude, 6),
                        "spd": round(self.movement_speed, 1),
                        "dir": int(self.direction) % 360
                    }
                }
                
                # Publish location to MQTT
                topic = f"pettracker/{self.device_id}/location"
                self._publish_mqtt(topic, message)
                logger.info(f"Published location: lat={self.latitude:.6f}, lon={self.longitude:.6f}")
                
                # Wait for the next interval
                await asyncio.sleep(self.location_interval)
                
            except asyncio.CancelledError:
                logger.info("Location loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in location loop: {e}")
                await asyncio.sleep(1)  # Brief delay before retry
    
    async def _send_heartbeat_loop(self):
        """
        Send heartbeat messages every self.heartbeat_interval seconds
        """
        logger.info(f"Starting heartbeat loop (every {self.heartbeat_interval}s)")
        
        while self.running:
            try:
                # Create heartbeat message
                message = {
                    "device_id": self.device_id,
                    "timestamp": self._get_timestamp(),
                    "event": "heartbeat",
                    "status": "active",
                    "battery": random.randint(60, 100)  # Simulate battery level
                }
                
                # Publish heartbeat to MQTT
                topic = f"pettracker/{self.device_id}/heartbeat"
                self._publish_mqtt(topic, message)
                logger.info(f"Published heartbeat for device {self.device_id}")
                
                # Wait for the next interval
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                logger.info("Heartbeat loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(1)  # Brief delay before retry
    
    async def _send_status_loop(self):
        """
        Send status updates every self.status_interval seconds
        """
        logger.info(f"Starting status update loop (every {self.status_interval}s)")
        
        while self.running:
            try:
                # Create status message
                message = {
                    "d": self.device_id,
                    "t": self._get_timestamp(),
                    "s": "online",
                    "b": random.randint(60, 100),  # Battery level
                    "m": "normal"  # Mode: normal, power_save, etc.
                }
                
                # Publish status to MQTT
                topic = f"pettracker/{self.device_id}/status"
                self._publish_mqtt(topic, message)
                logger.info(f"Published status for device {self.device_id}")
                
                # Wait for the next interval
                await asyncio.sleep(self.status_interval)
                
            except asyncio.CancelledError:
                logger.info("Status loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in status loop: {e}")
                await asyncio.sleep(1)  # Brief delay before retry
    
    def _update_location(self):
        """Update location to simulate realistic movement"""
        # Potentially change direction with some probability
        if random.random() < self.direction_change_probability:
            # Small random change in direction
            self.direction += random.uniform(-30, 30)
            self.direction %= 360  # Keep within 0-360 degrees
        
        # Calculate movement distance with some variation
        distance_meters = self.movement_speed * self.location_interval
        distance_variation = random.uniform(1-self.movement_variation, 1+self.movement_variation)
        adjusted_distance = distance_meters * distance_variation
        
        # Convert distance from meters to degrees
        # This is a simplified conversion that works for small distances
        # 1 degree of latitude is approximately 111,111 meters
        # 1 degree of longitude varies with latitude
        lat_change = adjusted_distance * math.cos(math.radians(self.direction)) / 111111
        lon_change = (adjusted_distance * math.sin(math.radians(self.direction)) / 
                      (111111 * math.cos(math.radians(self.latitude))))
        
        # Update coordinates
        self.latitude += lat_change
        self.longitude += lon_change
        
        # Ensure latitude is within valid range (-90 to 90)
        self.latitude = max(-90, min(90, self.latitude))
        
        # Ensure longitude is within valid range (-180 to 180)
        self.longitude = max(-180, min(180, self.longitude))
        
        logger.debug(f"Updated location: lat={self.latitude:.6f}, lon={self.longitude:.6f}, dir={self.direction:.1f}")
    
    def _publish_mqtt(self, topic, message):
        """Publish a message to MQTT"""
        try:
            # Check if MQTT client exists and is connected
            if not self.mqtt_client:
                logger.error("Cannot publish - MQTT client not initialized")
                return False
                
            if not self.mqtt_client.is_connected():
                logger.error("Cannot publish - MQTT client not connected")
                # Try to reconnect if the client exists but is not connected
                logger.info("Attempting to reconnect to MQTT broker...")
                try:
                    self.mqtt_client.reconnect()
                    # Wait briefly to see if connection is established
                    time.sleep(1)
                    if not self.mqtt_client.is_connected():
                        logger.error("Reconnection attempt failed")
                        return False
                    logger.info("Successfully reconnected to MQTT broker")
                except Exception as e:
                    logger.error(f"Failed to reconnect to MQTT broker: {e}")
                    return False
            
            # Convert message to JSON string
            payload = json.dumps(message)
            
            # Publish with QoS 1 (at least once delivery)
            result = self.mqtt_client.publish(topic, payload, qos=1)
            
            # Check result
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(f"Failed to publish to {topic}: {result.rc}")
                return False
                
            logger.debug(f"Successfully published to {topic}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing message to {topic}: {e}")
            return False
    
    def _get_timestamp(self):
        """Return a standardized ISO-8601 timestamp in UTC with 'Z' suffix"""
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


async def main(config):
    """Main entry point"""
    simulator = GPSTrackingSimulator(config)
    
    try:
        await simulator.start()
        
        # Keep running until interrupted
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Simulator interrupted by user")
    except Exception as e:
        logger.error(f"Simulator error: {e}")
    finally:
        await simulator.stop()
        logger.info("Clean shutdown completed")


if __name__ == "__main__":
    import argparse
    import yaml
    
    parser = argparse.ArgumentParser(description="PetTracker GPS Simulator")
    parser.add_argument("-c", "--config", default="config.yaml", help="Path to config file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Load configuration
    try:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
        logger.info(f"Loaded configuration from {args.config}")
    except Exception as e:
        logger.error(f"Error loading configuration from {args.config}: {e}")
        logger.info("Using default configuration")
        config = {
            "mqtt": {
                "broker_url": "test.mosquitto.org",
                "broker_port": 1883
            },
            "device": {
                "device_id": "123456",
                "start_lat": 14.072275,
                "start_lon": -87.192136
            },
            "simulation": {
                "location_interval": 5,
                "heartbeat_interval": 30,
                "status_interval": 300,
                "movement_speed": 5,
                "direction_change_probability": 0.2,
                "movement_variation": 0.3
            }
        }
    
    # Run the simulator
    asyncio.run(main(config))