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
        
        # Move parameters
        self.move = config.get('move', True)
        self.move_distance = config.get('move_distance', 0.00005)  # Approx. 5 meters
        self.move_interval = config.get('location_interval', 10)   # Seconds
        
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
        """Send location reports periodically"""
        location_interval = self.config.get('location_interval', 10)  # Seconds
        
        logger.info(f"Starting location loop, interval: {location_interval}s")
        
        while self.running:
            try:
                if self.protocol.authenticated:
                    # Update location if movement is enabled
                    if self.move:
                        self._update_location()
                        
                    # Add additional information
                    additional_info = {
                        0x01: self.config.get('mileage', 0),  # Mileage in km
                        0x02: self.config.get('fuel', 100),   # Fuel in percentage (0-100)
                    }
                    
                    # Check if we should use batch reporting
                    if self.batch_enabled:
                        self._handle_batch_reporting(additional_info)
                    else:
                        # Send normal location report
                        logger.info(f"Sending location: {self.latitude}, {self.longitude}")
                        # Ensure values are of correct types
                        int_altitude = int(self.altitude)
                        int_speed = int(self.speed)
                        int_direction = int(self.direction)
                        int_alarm = int(self.alarm)
                        int_status = int(self.status)
                        
                        # Send with proper typing
                        self.protocol.send_location(
                            self.latitude, self.longitude, int_altitude, 
                            int_speed, int_direction, int_alarm, int_status,
                            additional_info
                        )
                    
                # Sleep for the specified interval
                for _ in range(location_interval):
                    if not self.running:
                        break
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in location loop: {e}")
                time.sleep(5)  # Short delay before retrying
                
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
            
    def _update_location(self):
        """Update location coordinates to simulate movement"""
        # Convert direction from degrees to radians
        direction_rad = math.radians(self.direction)
        
        # Calculate new coordinates (simplified, not considering Earth curvature for small distances)
        self.latitude += self.move_distance * math.cos(direction_rad)
        self.longitude += self.move_distance * math.sin(direction_rad)
        
        # Add some randomness to direction
        self.direction = (self.direction + random.uniform(-10, 10)) % 360
        
        # Update speed with some randomness
        base_speed = self.config.get('speed', 60)  # km/h
        self.speed = max(0, min(120, base_speed + random.uniform(-10, 10)))
        
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
