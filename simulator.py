#!/usr/bin/env python3
"""
JT/T 808-2013 GPS Tracking Simulator

This script simulates a GPS tracking device using the JT/T 808-2013 protocol.
It connects to a server, registers, authenticates, and sends location updates.
"""
import sys
import os
import time
import random
import logging
import argparse
import json
import threading
from datetime import datetime
import math
from jt808.protocol import JT808Protocol
from jt808.constants import StatusBit, AlarmFlag

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('jt808-simulator')

class GPSTrackingSimulator:
    """
    GPS Tracking Simulator
    
    Simulates a GPS tracking device using the JT/T 808-2013 protocol.
    """
    def __init__(self, config):
        """
        Initialize the simulator
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.device_id = config['device_id']
        self.server_ip = config['server_ip']
        self.server_port = config['server_port']
        self.protocol = JT808Protocol(self.device_id, self.server_ip, self.server_port, logger)
        self.running = False
        self.location_thread = None
        self.heartbeat_thread = None
        self.connection_thread = None
        self.monitor_thread = None
        
        # Connection management
        self.connection_check_interval = config.get('connection_check_interval', 5)  # Seconds
        self.reconnect_interval = config.get('reconnect_interval', 5)  # Initial reconnect delay
        self.max_reconnect_interval = config.get('max_reconnect_interval', 60)  # Max reconnect delay
        self.threads_started = False
        
        # Current location - ensure all values are properly typed
        self.latitude = float(config.get('start_latitude', 15.5042))  # Honduras as default
        self.longitude = float(config.get('start_longitude', -88.0250))  # Honduras as default
        self.altitude = int(config.get('altitude', 100))
        self.speed = int(config.get('speed', 0))
        self.direction = int(config.get('direction', 0))
        
        # Position tracking for delta filtering
        self.min_position_delta = float(config.get('min_position_delta', 5.0))  # Minimum movement in meters
        self.should_send_location = True  # Flag to indicate if we should send location update
        self.last_sent_position = {
            'lat': self.latitude,
            'lon': self.longitude,
            'timestamp': time.time()
        }
        
        # Move parameters
        self.move = config.get('move', True)
        self.move_distance = config.get('move_distance', 0.00005)  # Approx. 5 meters
        self.move_interval = config.get('location_interval', 60)   # Changed to 60 seconds default
        
        # Position filtering parameters already initialized above
        # No need to set min_position_delta and should_send_location again
        
        # MQTT direct publishing settings 
        self.publish_binary_payload = config.get('publish_binary_payload', True)
        
        # Status and alarm flags
        self.status = config.get('status', StatusBit.ACC_ON | StatusBit.LOCATION_FIXED)
        self.alarm = config.get('alarm', 0)
        
        # Registration info
        self.province_id = config.get('province_id', 0)
        self.city_id = config.get('city_id', 0)
        self.manufacturer_id = config.get('manufacturer_id', 'SIMUL')
        self.terminal_model = config.get('terminal_model', 'SIM808')
        self.terminal_id = config.get('terminal_id', 'SIM0001')
        self.license_plate = config.get('license_plate', 'DEMO')
        
        # Batch report settings
        self.batch_enabled = config.get('batch_enabled', False)
        self.batch_size = config.get('batch_size', 5)
        self.batch_count = 0
        self.batch_locations = []
        
    def start(self):
        """Start the simulator with reconnection capability"""
        if self.running:
            logger.info("Simulator is already running")
            return
            
        logger.info(f"Starting GPS simulator with device ID: {self.device_id}")
        self.running = True
        
        # Start connection management thread
        self.connection_thread = threading.Thread(target=self._connection_manager)
        self.connection_thread.daemon = True
        self.connection_thread.start()
        
        # Start monitor thread for server messages
        self.monitor_thread = threading.Thread(target=self._message_monitor)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
    def _connection_manager(self):
        """Manage connection with reconnection logic"""
        backoff_time = self.reconnect_interval
        
        while self.running:
            try:
                # Check if we need to reconnect
                if not self.protocol.connected:
                    logger.info(f"Connecting to server at {self.server_ip}:{self.server_port}...")
                    
                    # Attempt connection
                    if self.protocol.connect():
                        logger.info("Connected to server")
                        backoff_time = self.reconnect_interval  # Reset backoff time on success
                        
                        # Run registration/authentication sequence
                        if self._register_and_authenticate():
                            # Start data transmission threads if they're not running
                            if not self.threads_started:
                                self._start_data_threads()
                                self.threads_started = True
                    else:
                        # Connection failed, wait and retry
                        logger.warning(f"Connection failed, retrying in {backoff_time} seconds...")
                        time.sleep(backoff_time)
                        # Exponential backoff with max cap
                        backoff_time = min(backoff_time * 2, self.max_reconnect_interval)
                        continue
                
                # Check connection health periodically
                time.sleep(self.connection_check_interval)
                
                # If we detect a disconnection in the protocol layer, log it 
                if not self.protocol.connected and self.threads_started:
                    logger.warning("Connection lost, will attempt to reconnect...")
                    # Reset authentication state
                    self.protocol.authenticated = False
                    self.protocol.auth_code = None
                    
            except Exception as e:
                logger.error(f"Error in connection manager: {e}")
                time.sleep(self.reconnect_interval)
    
    def _register_and_authenticate(self):
        """Handle registration and authentication process"""
        try:
            # Register the terminal
            logger.info("Registering terminal...")
            if not self.protocol.register(
                self.province_id, self.city_id, self.manufacturer_id, 
                self.terminal_model, self.terminal_id, 0, self.license_plate
            ):
                logger.error("Failed to send registration message")
                return False
                
            # Wait for authentication code (registration response)
            timeout = time.time() + 30  # 30 seconds timeout
            while self.protocol.auth_code is None and time.time() < timeout and self.protocol.connected:
                time.sleep(0.1)
                
            if not self.protocol.connected:
                logger.error("Connection lost during registration")
                return False
                
            if self.protocol.auth_code is None:
                logger.warning("No authentication code received, using default code '123456'")
                self.protocol.auth_code = "123456"
                
            logger.info(f"Received authentication code: {self.protocol.auth_code}")
            
            # Authenticate
            if not self.protocol.authenticated:
                logger.info("Authenticating terminal...")
                if not self.protocol.authenticate(self.protocol.auth_code):
                    logger.error("Failed to send authentication message")
                    return False
                    
                # Wait for authentication
                timeout = time.time() + 10  # 10 seconds timeout
                while not self.protocol.authenticated and time.time() < timeout and self.protocol.connected:
                    time.sleep(0.1)
                    
                if not self.protocol.connected:
                    logger.error("Connection lost during authentication")
                    return False
                    
                if not self.protocol.authenticated:
                    logger.warning("Authentication response not received, proceeding anyway for testing purposes")
                    # Force authentication status for testing purposes
                    self.protocol.authenticated = True
            
            logger.info("Authentication successful")
            return True
            
        except Exception as e:
            logger.error(f"Error in registration/authentication: {e}")
            return False
    
    def _start_data_threads(self):
        """Start the heartbeat and location threads"""
        logger.info("Starting data transmission threads")
        
        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        
        # Start location reporting thread
        self.location_thread = threading.Thread(target=self._location_loop)
        self.location_thread.daemon = True
        self.location_thread.start()
        
    def _message_monitor(self):
        """Monitor for messages from the server"""
        while self.running:
            try:
                if self.protocol.connected:
                    message = self.protocol.receive_message(timeout=1)
                    if message:
                        logger.info(f"Received message: ID={message.msg_id:04X}, len(body)={len(message.body)}")
                else:
                    # Don't consume CPU when disconnected
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in message monitor: {e}")
                time.sleep(1)
        
    def stop(self):
        """Stop the simulator"""
        if not self.running:
            return
            
        self.running = False
        
        # Send logout message
        if self.protocol.authenticated:
            logger.info("Sending logout message...")
            self.protocol.logout()
            
        # Disconnect from the server
        self.protocol.disconnect()
        
        logger.info("Simulator stopped")
        
    def _heartbeat_loop(self):
        """Send heartbeat messages periodically"""
        heartbeat_interval = self.config.get('heartbeat_interval', 60)  # Seconds
        
        logger.info(f"Starting heartbeat loop, interval: {heartbeat_interval}s")
        
        while self.running:
            try:
                if self.protocol.authenticated:
                    logger.info("Sending heartbeat...")
                    self.protocol.send_heartbeat()
                    
                # Sleep for the specified interval
                for _ in range(heartbeat_interval):
                    if not self.running:
                        break
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                time.sleep(5)  # Short delay before retrying
                
    def _location_loop(self):
        """Send location reports periodically with dynamic intervals based on pet activity"""
        # Get configuration parameters for dynamic intervals
        interval_fast = int(self.config.get('interval_fast', 5))  # 5 seconds when fast moving
        interval_walking = int(self.config.get('interval_walking', 60))  # 60 seconds when walking
        interval_resting = int(self.config.get('interval_resting', 300))  # 300 seconds when resting
        speed_threshold_fast = float(self.config.get('speed_threshold_fast', 20))  # km/h
        speed_threshold_walking = float(self.config.get('speed_threshold_walking', 5))  # km/h
        
        # Initial interval starts at walking speed
        location_interval = interval_walking
        self.min_position_delta = float(self.config.get('min_position_delta', 10.0))  # Minimum movement in meters (now 10m)
        
        logger.info(f"Starting location loop with dynamic intervals:")
        logger.info(f"  - Fast moving: {interval_fast}s (speed > {speed_threshold_fast} km/h)")
        logger.info(f"  - Walking: {interval_walking}s (speed > {speed_threshold_walking} km/h)")
        logger.info(f"  - Resting: {interval_resting}s (speed <= {speed_threshold_walking} km/h)")
        logger.info(f"  - Min position delta: {self.min_position_delta}m")
        
        # Import mqtt client if we'll be publishing directly
        mqtt_client = None
        if self.publish_binary_payload:
            try:
                import paho.mqtt.client as mqtt
                # Create MQTT client for direct publishing
                mqtt_client = mqtt.Client()
                # Configure MQTT connection
                mqtt_host = self.config.get('mqtt_host', 'localhost')
                mqtt_port = self.config.get('mqtt_port', 1883)
                mqtt_user = self.config.get('mqtt_user', '')
                mqtt_password = self.config.get('mqtt_password', '')
                
                # Set credentials if provided
                if mqtt_user and mqtt_password:
                    mqtt_client.username_pw_set(mqtt_user, mqtt_password)
                    
                # Connect to broker
                logger.info(f"Connecting to MQTT broker at {mqtt_host}:{mqtt_port}")
                mqtt_client.connect(mqtt_host, mqtt_port)
                mqtt_client.loop_start()
                logger.info("Connected to MQTT broker for direct binary publishing")
            except Exception as e:
                logger.error(f"Failed to setup MQTT client for direct publishing: {e}")
                mqtt_client = None
        
        # Use a shorter check interval for more responsive movement detection
        check_interval = min(max(interval_fast / 2, 1), 15)  # Between 1-15 seconds
        next_forced_update = time.time() + location_interval  # Time when we'll force an update
        current_activity = "walking"  # Start with walking state
        
        while self.running:
            try:
                if self.protocol.authenticated:
                    # Update location if movement is enabled
                    if self.move:
                        # Update position and check if we should send based on movement
                        self._update_location()
                        
                    # Dynamically adjust location_interval based on pet activity (speed)
                    current_speed = self.speed  # Current speed in km/h
                    
                    # Also adjust distance thresholds based on activity level
                    if current_speed > speed_threshold_fast:
                        # Fast moving pet
                        new_interval = interval_fast
                        new_activity = "fast_moving"  # Match converter.py activity name
                        new_min_distance = float(self.config.get('fast_distance', 5.0))  # 5m threshold when fast moving
                    elif current_speed > speed_threshold_walking:
                        # Walking pet
                        new_interval = interval_walking
                        new_activity = "walking"
                        new_min_distance = float(self.config.get('walking_distance', 10.0))  # 10m threshold when walking
                    else:
                        # Resting pet
                        new_interval = interval_resting
                        new_activity = "resting"
                        new_min_distance = float(self.config.get('resting_distance', 15.0))  # 15m threshold when resting
                    
                    # Log if activity state changed
                    if new_activity != current_activity:
                        logger.info(f"Pet activity changed: {current_activity} -> {new_activity} (speed: {current_speed:.1f} km/h)")
                        logger.info(f"Adjusting reporting interval: {location_interval}s -> {new_interval}s")
                        logger.info(f"Adjusting distance threshold: {self.min_position_delta}m -> {new_min_distance}m")
                        current_activity = new_activity
                        location_interval = new_interval
                        self.min_position_delta = new_min_distance
                    
                    # Implement strict dual-gating: BOTH time AND distance must be satisfied
                    time_now = time.time()
                    time_threshold_met = time_now >= next_forced_update
                    distance_threshold_met = self.should_send_location  # This is set to True in _update_location when distance threshold is met
                    
                    # Check if we should send based on both thresholds
                    should_send = time_threshold_met and distance_threshold_met
                    
                    # Log detailed threshold status
                    if time_threshold_met and not distance_threshold_met:
                        logger.info(f"Time threshold met ({location_interval}s elapsed), but distance threshold ({self.min_position_delta}m) not met yet. Waiting for more movement.")
                    elif distance_threshold_met and not time_threshold_met:
                        time_remaining = next_forced_update - time_now
                        logger.info(f"Distance threshold ({self.min_position_delta}m) met, but time threshold not met yet. Waiting {time_remaining:.1f}s more.")
                    elif time_threshold_met and distance_threshold_met:
                        logger.info(f"Both time ({location_interval}s) and distance ({self.min_position_delta}m) thresholds met. Sending location update.")
                    else:
                        logger.info(f"Neither time nor distance threshold met. Time remaining: {next_forced_update - time_now:.1f}s, Distance moved: {self._calculate_distance(self.last_sent_position['lat'], self.last_sent_position['lon'], self.latitude, self.longitude):.2f}m")
                    
                    # Only send if BOTH thresholds (time and distance) are met
                    if should_send:
                        # Determine which additional info to include based on optimization settings
                        additional_info = {}
                        
                        # Check if we should optimize payload size
                        if self.config.get('optimize_payload', True):
                            # When optimizing, only include essential additional data
                            # For pets, mileage is probably the most important metric (distance traveled)
                            additional_info = {
                                0x01: self.config.get('mileage', 0),  # Mileage in km - essential for pets
                            }
                            
                            # Add battery level only if it's below 30% (important to report)
                            battery_level = self.config.get('battery_level', 100)
                            if battery_level <= 30:
                                additional_info[0x02] = battery_level
                        else:
                            # When not optimizing, include all additional information
                            additional_info = {
                                0x01: self.config.get('mileage', 0),  # Mileage in km
                                0x02: self.config.get('fuel', 100),   # Fuel/battery in percentage (0-100)
                            }
                        
                        # Check if we should use batch reporting
                        if self.batch_enabled:
                            self._handle_batch_reporting(additional_info)
                        else:
                            logger.info(f"Sending location: {self.latitude}, {self.longitude}")
                            # Ensure values are of correct types
                            int_altitude = int(self.altitude)
                            int_speed = int(self.speed)
                            int_direction = int(self.direction)
                            int_alarm = int(self.alarm)
                            int_status = int(self.status)
                            
                            # Send via protocol to TCP server
                            self.protocol.send_location(
                                self.latitude, self.longitude, int_altitude, 
                                int_speed, int_direction, int_alarm, int_status,
                                additional_info
                            )
                            
                            # Also publish directly to MQTT if configured
                            if mqtt_client and self.publish_binary_payload:
                                try:
                                    # Create a location message using the protocol
                                    from jt808.message import Message
                                    location_msg = Message.create_location_report(
                                        self.device_id, int_alarm, int_status, 
                                        self.latitude, self.longitude, int_altitude,
                                        int_speed, int_direction, None, additional_info
                                    )
                                    
                                    # Get binary payload
                                    binary_payload = location_msg.body
                                    
                                    # Format topic with device_id
                                    topic_template = self.config.get('mqtt_location_topic', 'jt808/{device_id}/location')
                                    topic = topic_template.replace('{device_id}', self.device_id)
                                    
                                    # Publish binary payload to MQTT
                                    mqtt_client.publish(topic, binary_payload)
                                    logger.info(f"Published binary location payload to MQTT topic: {topic}")
                                except Exception as e:
                                    logger.error(f"Failed to publish binary payload to MQTT: {e}")
                            
                            # Update last sent position tracking
                            self.last_sent_position = {
                                'lat': self.latitude,
                                'lon': self.longitude,
                                'timestamp': time.time()
                            }
                            # Reset the distance threshold flag - will only be set to True again when sufficient movement occurs
                            self.should_send_location = False
                            
                            # CRITICAL FIX: Reset the time threshold as well after successful sending
                            next_forced_update = time.time() + location_interval
                    else:
                        logger.debug(f"Skipping location update - position delta below threshold")
                        
                # Use shorter sleep intervals to check movement more frequently
                time.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Error in location loop: {e}")
                time.sleep(5)  # Short delay before retrying
                
        # Clean up MQTT client if it was created
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
                
    def _handle_batch_reporting(self, additional_info):
        """Handle batch reporting of location data"""
        # Add current location to batch
        self.batch_locations.append((
            self.latitude, self.longitude, self.altitude, 
            self.speed, self.direction, self.alarm, self.status,
            additional_info
        ))
        
        self.batch_count += 1
        logger.info(f"Added location to batch: {self.batch_count}/{self.batch_size}")
        
        # Send batch when we reach the desired size
        if len(self.batch_locations) >= self.batch_size:
            logger.info(f"Sending batch of {len(self.batch_locations)} locations")
            self.protocol.send_batch_location(self.batch_locations)
            self.batch_locations = []
            
            # Update last sent position tracking
            self.last_sent_position = {
                'lat': self.latitude,
                'lon': self.longitude,
                'timestamp': time.time()
            }
            # Reset the distance threshold flag after sending batch
            self.should_send_location = False
            
    def should_publish_location(self, current_lat, current_lon, current_time, current_speed):
        """
        Determine if a location update should be published based on dual-gating criteria
        
        Args:
            current_lat: Current latitude
            current_lon: Current longitude
            current_time: Current timestamp (float)
            current_speed: Current speed in km/h
            
        Returns:
            tuple: (should_publish, reason, time_threshold, distance_threshold)
        """
        # Get thresholds based on current speed/activity
        if current_speed > float(self.config.get('speed_threshold_fast', 20)):
            # Fast moving
            time_threshold = float(self.config.get('fast_interval', 5))
            distance_threshold = float(self.config.get('fast_distance', 5.0))
            activity = "fast_moving"
        elif current_speed > float(self.config.get('speed_threshold_walking', 5)):
            # Walking
            time_threshold = float(self.config.get('walking_interval', 60))
            distance_threshold = float(self.config.get('walking_distance', 10.0))
            activity = "walking"
        else:
            # Resting
            time_threshold = float(self.config.get('resting_interval', 300))
            distance_threshold = float(self.config.get('resting_distance', 15.0))
            activity = "resting"
        
        # Check time threshold - must be at least the minimum interval since last send
        time_since_last = current_time - self.last_sent_position['timestamp']
        time_threshold_met = time_since_last >= time_threshold
        
        # Check distance threshold - must have moved minimum distance since last send
        distance_moved = self._calculate_distance(
            self.last_sent_position['lat'], 
            self.last_sent_position['lon'],
            current_lat,
            current_lon
        )
        distance_threshold_met = distance_moved >= distance_threshold
        
        # Both thresholds must be met (AND logic)
        should_publish = time_threshold_met and distance_threshold_met
        
        # Prepare detailed reason for logging
        if should_publish:
            reason = f"Both time ({time_threshold}s, elapsed={time_since_last:.1f}s) and distance ({distance_threshold}m, moved={distance_moved:.2f}m) thresholds met for {activity}"
        elif time_threshold_met and not distance_threshold_met:
            reason = f"Time threshold met ({time_threshold}s, elapsed={time_since_last:.1f}s), but distance threshold ({distance_threshold}m) not met (moved only {distance_moved:.2f}m)"
        elif distance_threshold_met and not time_threshold_met:
            reason = f"Distance threshold met ({distance_threshold}m, moved={distance_moved:.2f}m), but time threshold ({time_threshold}s) not met (elapsed only {time_since_last:.1f}s)"
        else:
            reason = f"Neither threshold met: time={time_since_last:.1f}s/{time_threshold}s, distance={distance_moved:.2f}m/{distance_threshold}m"
        
        return (should_publish, reason, time_threshold, distance_threshold)

    def _update_location(self):
        """Update location coordinates to simulate movement with activity-based thresholds"""
        # Convert direction from degrees to radians
        direction_rad = math.radians(self.direction)
        
        # Store previous coordinates
        old_lat = self.latitude
        old_lon = self.longitude
        
        # Calculate new coordinates (simplified, not considering Earth curvature for small distances)
        self.latitude += self.move_distance * math.cos(direction_rad)
        self.longitude += self.move_distance * math.sin(direction_rad)
        
        # Add some randomness to direction
        self.direction = (self.direction + random.uniform(-10, 10)) % 360
        
        # Update speed with some randomness
        base_speed = self.config.get('speed', 60)  # km/h
        self.speed = max(0, min(120, base_speed + random.uniform(-10, 10)))
        
        # Calculate distance moved from last sent position (not just previous step)
        distance_from_last_sent = self._calculate_distance(
            self.last_sent_position['lat'], 
            self.last_sent_position['lon'], 
            self.latitude, 
            self.longitude
        )
        
        # Calculate distance from last step (for logging)
        distance_moved = self._calculate_distance(old_lat, old_lon, self.latitude, self.longitude)
        
        # Determine activity level based on current speed
        speed_threshold_fast = float(self.config.get('speed_threshold_fast', 20))  # km/h
        speed_threshold_walking = float(self.config.get('speed_threshold_walking', 5))  # km/h
        
        # Set activity level and the corresponding distance threshold
        if self.speed > speed_threshold_fast:
            # Fast moving pet
            activity_level = "fast_moving"
            min_distance_threshold = float(self.config.get('fast_distance', 5.0))  # 5 meters
        elif self.speed > speed_threshold_walking:
            # Walking pet
            activity_level = "walking"
            min_distance_threshold = float(self.config.get('walking_distance', 10.0))  # 10 meters
        else:
            # Resting pet
            activity_level = "resting"
            min_distance_threshold = float(self.config.get('resting_distance', 15.0))  # 15 meters
        
        # Apply activity-based distance threshold for sending updates
        if distance_from_last_sent >= min_distance_threshold:
            logger.info(f"Moved {distance_from_last_sent:.2f}m from last sent position, exceeding {activity_level} threshold of {min_distance_threshold:.1f}m")
            self.should_send_location = True
        else:
            logger.info(f"[{activity_level}] Step moved: {distance_moved:.2f}m, total from last sent: {distance_from_last_sent:.2f}m (below threshold of {min_distance_threshold:.1f}m)")
            
    def _calculate_distance(self, lat1, lon1, lat2, lon2):
        """
        Calculate distance between two points in meters
        Using Haversine formula
        """
        # Earth radius in meters
        R = 6371000.0
        
        # Convert coordinates from degrees to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
        
        # Haversine formula
        dlon = lon2_rad - lon1_rad
        dlat = lat2_rad - lat1_rad
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        return distance
        
    def _monitor_received_messages(self):
        """Monitor for messages received from the server"""
        while self.running:
            try:
                message = self.protocol.receive_message(timeout=1)
                if message:
                    logger.info(f"Received message: ID={message.msg_id:04X}, len(body)={len(message.body)}")
            except Exception as e:
                logger.error(f"Error in message monitor: {e}")

def load_config():
    """Load configuration from file or use defaults"""
    default_config = {
        'device_id': '123456789012',
        'server_ip': '127.0.0.1',  # Use localhost to connect to the server
        'server_port': 8008,      # Updated to match converter port
        'start_latitude': 15.5042,  # Honduras coordinates
        'start_longitude': -88.0250,  # Honduras coordinates
        'altitude': 100,
        'speed': 60,
        'direction': 45,
        'move': True,
        'move_distance': 0.00005,
        'location_interval': 10,
        'heartbeat_interval': 60,
        'province_id': 11,
        'city_id': 1,
        'manufacturer_id': 'SIMUL',
        'terminal_model': 'SIM808',
        'terminal_id': 'SIM0001',
        'license_plate': 'DEMO',
        'batch_enabled': False,
        'batch_size': 5,
        'mileage': 10000,
        'fuel': 75
    }
    
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                loaded_config = json.load(f)
                # Update default config with loaded values
                default_config.update(loaded_config)
                logger.info("Loaded configuration from config.json")
    except Exception as e:
        logger.warning(f"Failed to load config.json: {e}")
        
    return default_config

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='JT/T 808-2013 GPS Tracking Simulator')
    
    parser.add_argument('-i', '--ip', help='Server IP address')
    parser.add_argument('-p', '--port', type=int, help='Server port')
    parser.add_argument('-d', '--device', help='Device ID (phone number)')
    parser.add_argument('-c', '--config', help='Path to config file')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    
    return parser.parse_args()

def main():
    """Main entry point"""
    args = parse_args()
    
    # Set log level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger('jt808').setLevel(logging.DEBUG)
        
    # Load configuration
    config = load_config()
    
    # Override with command line arguments
    if args.ip:
        config['server_ip'] = args.ip
    if args.port:
        config['server_port'] = args.port
    if args.device:
        config['device_id'] = args.device
    if args.config:
        try:
            with open(args.config, 'r') as f:
                custom_config = json.load(f)
                config.update(custom_config)
                logger.info(f"Loaded configuration from {args.config}")
        except Exception as e:
            logger.error(f"Failed to load {args.config}: {e}")
            return
            
    # Create and start the simulator
    simulator = GPSTrackingSimulator(config)
    
    try:
        simulator.start()
        
        # Keep the main thread running
        while simulator.running:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Stopping simulator...")
        simulator.stop()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        simulator.stop()

if __name__ == '__main__':
    main()
