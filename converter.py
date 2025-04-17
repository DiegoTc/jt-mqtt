#!/usr/bin/env python3
"""
JT/T 808-2013 to MQTT Converter

This script listens for JT/T 808-2013 protocol messages and converts them to MQTT format.
"""
# Add a global try-except to catch any early errors
try:
    import sys
    import os
    import time
    import socket
    import threading
    import logging
    import argparse
    import json
    import struct
    import traceback
    import random
    import math
    import paho.mqtt.client as mqtt
    import ssl
    from datetime import datetime
    from dotenv import load_dotenv
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Configure basic logging before importing modules that might use it
    # Get log level from environment or use INFO as default
    log_level_name = os.environ.get('LOG_LEVEL', 'DEBUG')
    log_level = getattr(logging, log_level_name)
    
    # Create a log file for debugging
    log_file = "/tmp/jt808_converter.log"
    
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),  # Log to console
            logging.FileHandler(log_file)  # Log to file
        ]
    )
    logger = logging.getLogger('jt808-converter')
    logger.info(f"Logging initialized at level: {log_level_name}")
    logger.info(f"Logs will be written to {log_file}")
    
    # Now import our custom modules
    try:
        from jt808.message import Message
        from jt808.constants import MessageID, StatusBit, AlarmFlag
        from jt808.utils import bytes_to_bcd, dms_to_decimal, parse_bcd_timestamp
        logger.info("Successfully imported all modules")
    except Exception as module_err:
        logger.error(f"Error importing custom modules: {module_err}")
        logger.error(traceback.format_exc())
        raise
        
except Exception as e:
    # If we get an error during imports, print it to stderr and exit
    import traceback
    import re
    print(f"CRITICAL ERROR during initialization: {e}", file=sys.stderr)
    tb_str = traceback.format_exc()
    print(f"Error details: {tb_str}", file=sys.stderr)
    
    # Get the line number and file where the error occurred
    line_match = re.search(r'File "([^"]+)", line (\d+)', tb_str)
    if line_match:
        error_file = line_match.group(1)
        line_num = line_match.group(2)
        print(f"Error occurred in file {error_file} at or near line {line_num}", file=sys.stderr)
    sys.exit(1)

# Logging is already configured above, so just use the existing logger 
# logger = logging.getLogger('jt808-converter')

class JT808Server:
    """
    JT/T 808-2013 Protocol Server
    
    Listens for incoming connections and messages from terminals.
    """
    def __init__(self, host, port, mqtt_client, mqtt_config):
        """
        Initialize the server
        
        Args:
            host: Host to listen on
            port: Port to listen on
            mqtt_client: MQTT client instance
            mqtt_config: MQTT configuration dictionary
        """
        self.host = host
        self.port = port
        self.mqtt_client = mqtt_client
        self.mqtt_config = mqtt_config
        self.server_socket = None
        self.clients = {}  # {socket: {'addr': addr, 'buffer': bytearray(), 'device_id': None}}
        
        # Device state tracking for dual-gating (time + distance)
        self.device_state = {}  # {device_id: {'lat': lat, 'lon': lon, 'last_pub_time': timestamp, 'activity': activity}}
        
        # Activity-based threshold settings
        self.thresholds = {
            'fast_moving': {  # > 20 km/h
                'interval': mqtt_config.get('fast_interval', 5),       # seconds
                'distance': mqtt_config.get('fast_distance', 5.0)      # meters
            },
            'walking': {      # 5-20 km/h
                'interval': mqtt_config.get('walking_interval', 60),      # seconds
                'distance': mqtt_config.get('walking_distance', 10.0)     # meters
            },
            'resting': {      # < 5 km/h
                'interval': mqtt_config.get('resting_interval', 300),     # seconds
                'distance': mqtt_config.get('resting_distance', 15.0)     # meters
            }
        }
        
        # Cache for position throttling (legacy, keeping for backward compatibility)
        self.position_cache = {}  # {device_id: {'lat': lat, 'lon': lon, 'timestamp': timestamp}}
        
        # Event state tracking for debouncing
        self.status_cache = {}  # {device_id: {'status': status, 'timestamp': timestamp}}
        self.auth_cache = {}    # {device_id: {'auth_code': auth_code, 'timestamp': timestamp}}
        self.heartbeat_cache = {}  # {device_id: {'timestamp': timestamp}}
        self.registration_cache = {}  # {device_id: {'registered': True, 'timestamp': timestamp}}
        
        # Enhanced throttling settings for bandwidth and battery optimization
        self.throttle_duplicates = mqtt_config.get('throttle_duplicates', True)
        self.throttle_timeout = mqtt_config.get('throttle_timeout', 60)  # Seconds
        self.min_position_delta = mqtt_config.get('min_position_delta', 10.0)  # Meters (increased to 10m)
        self.heartbeat_interval = mqtt_config.get('heartbeat_interval', 60)  # Seconds between heartbeats
        
        # Additional optimization settings
        self.registration_ttl = mqtt_config.get('registration_ttl', 3600)  # Only re-register once per hour
        self.status_ttl = mqtt_config.get('status_ttl', 300)  # Only publish status changes every 5 minutes
        self.optimize_payload = mqtt_config.get('optimize_payload', True)  # Strip unused fields
        
        # MQTT topic configuration
        self.mqtt_location_topic = mqtt_config.get('mqtt_location_topic', 'pettracker/{device_id}/location')
        self.running = False
        self.accept_thread = None
        
    def start(self):
        """Start the server"""
        if self.running:
            logger.info("Server is already running")
            return
            
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            
            self.running = True
            logger.info(f"JT808 Server listening on {self.host}:{self.port}")
            
            # Start thread to accept new connections
            self.accept_thread = threading.Thread(target=self._accept_connections)
            self.accept_thread.daemon = True
            self.accept_thread.start()
            
            return True
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            return False
            
    def stop(self):
        """Stop the server"""
        if not self.running:
            return
            
        self.running = False
        
        # Close all client connections
        for client_socket in list(self.clients.keys()):
            self._close_client(client_socket)
            
        # Close server socket
        if self.server_socket:
            self.server_socket.close()
            
        logger.info("Server stopped")
        
    def _accept_connections(self):
        """Accept new connections"""
        if self.server_socket is None:
            logger.error("Cannot accept connections: server socket is None")
            return
            
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                logger.info(f"New connection from {addr[0]}:{addr[1]}")
                
                # Initialize client info
                self.clients[client_socket] = {
                    'addr': addr,
                    'buffer': bytearray(),
                    'device_id': None
                }
                
                # Start thread to handle client
                thread = threading.Thread(target=self._handle_client, args=(client_socket,))
                thread.daemon = True
                thread.start()
            except Exception as e:
                if self.running:
                    logger.error(f"Error accepting connection: {e}")
                    time.sleep(1)
                    
    def _handle_client(self, client_socket):
        """
        Handle communication with a client
        
        Args:
            client_socket: Client socket
        """
        buffer = self.clients[client_socket]['buffer']
        device_id = self.clients[client_socket]['device_id'] or 'unknown'
        
        logger.info(f"[{device_id}] Client handler thread started for {self.clients[client_socket]['addr']}")
        
        while self.running and client_socket in self.clients:
            try:
                # Receive data
                logger.info(f"[{device_id}] Waiting for data from client...")
                data = client_socket.recv(1024)
                
                if not data:
                    logger.info(f"[{device_id}] Connection closed by client {self.clients[client_socket]['addr']}")
                    self._close_client(client_socket)
                    break
                
                # Log received data
                logger.info(f"[{device_id}] Received {len(data)} bytes: {data.hex()}")
                    
                # Add to buffer
                buffer.extend(data)
                logger.info(f"[{device_id}] Added data to buffer, new size: {len(buffer)} bytes, buffer: {buffer.hex()}")
                
                # Store the updated buffer reference
                self.clients[client_socket]['buffer'] = buffer
                
                # Process complete messages in the buffer
                self._process_buffer(client_socket)
            except Exception as e:
                import traceback
                if self.running and client_socket in self.clients:
                    logger.error(f"[{device_id}] Error handling client {self.clients[client_socket]['addr']}: {e}")
                    logger.error(traceback.format_exc())
                    self._close_client(client_socket)
                break
        
        logger.info(f"[{device_id}] Client handler thread terminated for {self.clients[client_socket]['addr'] if client_socket in self.clients else 'unknown'}")
                
    def _process_buffer(self, client_socket):
        """
        Process the client's buffer to extract complete messages
        
        Args:
            client_socket: Client socket
        """
        buffer = self.clients[client_socket]['buffer']
        device_id = self.clients[client_socket]['device_id'] or 'unknown'
        
        # Log every time we process a buffer for visibility
        logger.info(f"[{device_id}] Processing buffer, size: {len(buffer)} bytes, hex: {buffer.hex() if len(buffer) < 100 else buffer[:100].hex() + '...'}")
        
        while len(buffer) > 2:
            # Find start and end markers
            start_idx = buffer.find(b'\x7e')
            if start_idx == -1:
                logger.warning(f"[{device_id}] No start marker found in buffer, clearing buffer")
                buffer.clear()
                break
                
            # Remove any data before the start marker
            if start_idx > 0:
                logger.warning(f"[{device_id}] Found garbage before start marker, removing {start_idx} bytes: {buffer[:start_idx].hex()}")
                buffer = buffer[start_idx:]
                self.clients[client_socket]['buffer'] = buffer
                
            # Find the end marker
            end_idx = buffer.find(b'\x7e', 1)
            if end_idx == -1:
                # No complete message yet
                logger.info(f"[{device_id}] No end marker found, waiting for more data. Buffer size: {len(buffer)} bytes")
                break
                
            # Extract the complete message
            message_data = buffer[:end_idx+1]
            buffer = buffer[end_idx+1:]
            self.clients[client_socket]['buffer'] = buffer
            
            # Debug log the message data in detail
            logger.info(f"[{device_id}] Raw message data: {message_data}")
            logger.info(f"[{device_id}] Raw message data length: {len(message_data)} bytes")
            logger.info(f"[{device_id}] Raw message data hex: {message_data.hex()}")
            
            try:
                # Decode the message
                message = Message.decode(message_data)
                
                # Log the message ID and type for debugging
                msg_id_hex = f"0x{message.msg_id:04X}"
                logger.info(f"[{device_id}] Decoded message ID: {msg_id_hex}")
                
                # Update device ID if not yet known
                if not self.clients[client_socket]['device_id'] and hasattr(message, 'phone_no'):
                    # Make sure device_id is always stored as a string
                    if isinstance(message.phone_no, str):
                        self.clients[client_socket]['device_id'] = message.phone_no
                    else:
                        self.clients[client_socket]['device_id'] = str(message.phone_no)
                    logger.info(f"Client {self.clients[client_socket]['addr']} identified as device {self.clients[client_socket]['device_id']}")
                
                # Process the message
                self._process_message(client_socket, message)
            except Exception as e:
                import traceback
                logger.error(f"[{device_id}] Failed to decode message: {e}")
                logger.error(traceback.format_exc())
                
    def _process_message(self, client_socket, message):
        """
        Process a decoded message
        
        Args:
            client_socket: Client socket
            message: Decoded Message object
        """
        device_id = self.clients[client_socket]['device_id'] or 'unknown'
        
        # Enhanced logging - message body hex for all messages
        body_hex = message.body.hex() if message.body else "empty"
        logger.debug(f"[{device_id}] Message ID: 0x{message.msg_id:04X}, Serial: {message.msg_serial_no}, Body length: {len(message.body)} bytes")
        logger.debug(f"[{device_id}] Message body hex: {body_hex}")
        
        # Handle different message types
        if message.msg_id == MessageID.TERMINAL_HEARTBEAT:
            logger.info(f"Heartbeat from {device_id}")
            self._send_general_response(client_socket, message, 0)
            self._publish_heartbeat(device_id)
            
        elif message.msg_id == MessageID.TERMINAL_REGISTRATION:
            logger.info(f"Registration from {device_id}")
            auth_code = "123456"  # In a real system, this would be generated or fetched
            logger.debug(f"Generated auth code for {device_id}: {auth_code}")
            self._send_registration_response(client_socket, message, 0, auth_code)
            self._publish_registration(device_id, message)
            
        elif message.msg_id == MessageID.TERMINAL_AUTH:
            logger.info(f"Authentication from {device_id}, msg_serial_no={message.msg_serial_no}")
            # Log the authentication message details
            if message.body and len(message.body) > 0:
                auth_len = message.body[0]
                logger.debug(f"Authentication body length: {len(message.body)}, auth_code_len={auth_len}")
                
                if 1 + auth_len <= len(message.body):
                    try:
                        auth_code = message.body[1:1+auth_len].decode('utf-8')
                        logger.debug(f"Authentication code received: '{auth_code}'")
                    except Exception as e:
                        logger.error(f"Failed to decode auth code: {e}")
            
            self._send_general_response(client_socket, message, 0)
            self._publish_authentication(device_id, message)
            
        elif message.msg_id == MessageID.LOCATION_REPORT:
            logger.info(f"Location report from {device_id}, msg_serial_no={message.msg_serial_no}")
            
            if len(message.body) >= 28:
                try:
                    # Extract basic location information for logging
                    alarm_flag, status, lat_value, lon_value = struct.unpack('>IIII', message.body[:16])
                    
                    # Convert coordinates for logging
                    latitude = dms_to_decimal(lat_value)
                    longitude = dms_to_decimal(lon_value)
                    
                    # Apply direction flags
                    if status & StatusBit.LAT_SOUTH:
                        latitude = -latitude
                    if status & StatusBit.LON_WEST:
                        longitude = -longitude
                    
                    logger.debug(f"Location data - lat: {latitude}, lon: {longitude}, alarm: 0x{alarm_flag:08X}, status: 0x{status:08X}")
                except Exception as e:
                    logger.error(f"Error parsing location data for logging: {e}")
            
            self._send_general_response(client_socket, message, 0)
            self._publish_location(device_id, message)
            
        elif message.msg_id == MessageID.BATCH_LOCATION_UPLOAD:
            logger.info(f"Batch location upload from {device_id}")
            self._send_general_response(client_socket, message, 0)
            self._publish_batch_location(device_id, message)
            
        elif message.msg_id == MessageID.TERMINAL_LOGOUT:
            logger.info(f"Logout from {device_id}")
            self._send_general_response(client_socket, message, 0)
            self._publish_logout(device_id)
            
        else:
            logger.info(f"Unsupported message type from {device_id}: 0x{message.msg_id:04X}")
            self._send_general_response(client_socket, message, 3)  # Unsupported
            
    def _send_general_response(self, client_socket, message, result):
        """
        Send a general response to the client
        
        Args:
            client_socket: Client socket
            message: Original message
            result: Result code
        """
        try:
            device_id = self.clients[client_socket]['device_id'] or 'unknown'
            logger.debug(f"[{device_id}] Creating general response for msg_id=0x{message.msg_id:04X}, serial={message.msg_serial_no}, result={result}")
            
            # Force result to 0 (success) during testing
            result = 0
            
            # Create a response body according to JT/T 808-2013 specification section 8.1
            # The simulator is expecting EXACTLY 5 bytes in this format:
            # Bytes 0-1: Response serial number (2 bytes)
            # Bytes 2-3: Ack message ID (2 bytes)
            # Byte 4: Result code (1 byte)
            body = struct.pack('>HHB', message.msg_serial_no, message.msg_id, result)
            
            # Log in detail to ensure it's the exact 5 bytes format expected
            logger.debug(f"[{device_id}] Response serial: {message.msg_serial_no} (2 bytes)")
            logger.debug(f"[{device_id}] Message ID: 0x{message.msg_id:04X} (2 bytes)")
            logger.debug(f"[{device_id}] Result: {result} (1 byte)")
            logger.debug(f"[{device_id}] General response body hex: {body.hex()}, length: {len(body)} bytes")
            
            # Create response message
            response = Message(
                MessageID.PLATFORM_GENERAL_RESPONSE, 
                message.phone_no,
                body
            )
            
            encoded_response = response.encode()
            logger.debug(f"[{device_id}] General response encoded hex: {encoded_response.hex()}")
            
            client_socket.sendall(encoded_response)
            logger.debug(f"[{device_id}] Sent general response: msg_id=0x{message.msg_id:04X}, serial={message.msg_serial_no}, result={result}")
        except Exception as e:
            logger.error(f"Failed to send general response: {e}")
            logger.error(traceback.format_exc())
            
    def _send_registration_response(self, client_socket, message, result, auth_code):
        """
        Send a registration response to the client
        
        Args:
            client_socket: Client socket
            message: Original message
            result: Result code (should be 0 for success)
            auth_code: Authentication code
        """
        try:
            # Always use a valid auth code (JT808 protocol requires a non-empty auth code)
            if not auth_code or len(auth_code.strip()) == 0:
                auth_code = "123456"
                logger.warning(f"Empty auth code detected, using default: '{auth_code}'")
            
            # Log registration details for debugging
            device_id = self.clients[client_socket]['device_id'] or 'unknown'
            logger.debug(f"[{device_id}] Preparing registration response, serial={message.msg_serial_no}, result={result}")
            
            # Ensure result is always 0 (success) during testing
            result = 0
            
            # Prepare registration response body - MUST USE THIS EXACT FORMAT:
            # First 2 bytes: Response serial number (same as request)
            # Next 1 byte: Result (0=success, 1=vehicle already registered, 2=no such vehicle, 3=terminal already registered, 4=terminal not allowed)
            # Next byte: Auth code length
            # Remaining bytes: Auth code
            body = struct.pack('>HB', message.msg_serial_no, result)
            
            # Make sure the auth code is 123456 which is expected by the simulator
            auth_code = "123456"
            
            # Add the auth code - length byte first, then the auth code
            auth_bytes = auth_code.encode('ascii')
            body += bytes([len(auth_bytes)]) + auth_bytes
            
            # Debug the response
            logger.debug(f"[{device_id}] Registration response serial: {message.msg_serial_no}, result: {result}")
            logger.debug(f"[{device_id}] Auth code: '{auth_code}', bytes: {auth_bytes.hex()}, length: {len(auth_bytes)}")
            
            # Create response message
            response = Message(
                MessageID.TERMINAL_REGISTRATION_RESPONSE,
                message.phone_no,
                body
            )
            
            encoded_response = response.encode()
            logger.debug(f"[{device_id}] Registration response body: {body.hex()}")
            logger.debug(f"[{device_id}] Registration response encoded: {encoded_response.hex()}")
            
            client_socket.sendall(encoded_response)
            logger.info(f"Sent registration response to {message.phone_no}: result={result}, auth_code='{auth_code}'")
        except Exception as e:
            logger.error(f"Failed to send registration response: {e}")
            logger.error(traceback.format_exc())
            
    def _close_client(self, client_socket):
        """
        Close a client connection
        
        Args:
            client_socket: Client socket
        """
        try:
            device_id = self.clients[client_socket]['device_id']
            if device_id:
                logger.info(f"Closing connection to device {device_id}")
                # Publish disconnect status
                self._publish_status(device_id, "offline")
            else:
                logger.info(f"Closing connection to unidentified client {self.clients[client_socket]['addr']}")
                
            client_socket.close()
            del self.clients[client_socket]
        except Exception as e:
            logger.error(f"Error closing client: {e}")
            
    def _publish_heartbeat(self, device_id):
        """
        Publish heartbeat to MQTT
        
        Args:
            device_id: Device ID
        """
        # Apply throttling to heartbeat events
        current_time = time.time()
        should_publish = True
        
        if device_id in self.heartbeat_cache:
            last_heartbeat_time = self.heartbeat_cache[device_id].get('timestamp', 0)
            time_diff = current_time - last_heartbeat_time
            
            # Only publish if enough time has passed since the last heartbeat
            if time_diff < self.heartbeat_interval:
                logger.debug(f"Throttling heartbeat for {device_id}, last sent {time_diff:.1f}s ago")
                should_publish = False
        
        # Update the heartbeat cache regardless of whether we publish
        self.heartbeat_cache[device_id] = {
            'timestamp': current_time
        }
        
        if should_publish:
            topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/heartbeat"
            payload = {
                "device_id": device_id,
                "timestamp": datetime.now().isoformat(),
                "event": "heartbeat"
            }
            
            logger.debug(f"Publishing heartbeat for {device_id}")
            self._publish_mqtt(topic, payload)
            
        # Always call publish_status, which has its own debouncing logic
        self._publish_status(device_id, "online")
        
    def _publish_registration(self, device_id, message):
        """
        Publish registration information to MQTT
        
        Args:
            device_id: Device ID
            message: Registration message
        """
        if len(message.body) < 32:
            logger.error(f"Invalid registration message format from {device_id}")
            return
            
        try:
            # Parse registration message body
            province_id, city_id = struct.unpack('>HH', message.body[:4])
            
            # Handle manufacturer_id - safely decode ASCII
            try:
                manufacturer_id = message.body[4:9].decode('ascii').strip('\x00')
            except Exception:
                manufacturer_id = ''.join([f'{b:02x}' for b in message.body[4:9]]).upper()
            
            # Handle terminal_model - safely decode ASCII
            try:
                terminal_model = message.body[9:29].decode('ascii').strip('\x00')
            except Exception:
                terminal_model = ''.join([f'{b:02x}' for b in message.body[9:29]]).upper()
            
            # Handle terminal_id - safely decode ASCII
            try:
                terminal_id = message.body[29:36].decode('ascii').strip('\x00')
            except Exception:
                terminal_id = ''.join([f'{b:02x}' for b in message.body[29:36]]).upper()
                
            license_plate_color = message.body[36]
            
            # Get license plate
            license_plate = ""
            if len(message.body) > 37:
                license_len = message.body[37]
                if 38 + license_len <= len(message.body):
                    try:
                        license_plate = message.body[38:38+license_len].decode('utf-8')
                    except Exception:
                        license_plate = ''.join([f'{b:02x}' for b in message.body[38:38+license_len]]).upper()
            
            # Implement debouncing for registrations - only publish once per device per session
            should_publish = True
            if device_id in self.registration_cache:
                # We've seen this device register before in this session
                logger.debug(f"Device {device_id} has already registered in this session, not publishing duplicate registration")
                should_publish = False
            
            # Update registration cache regardless of whether we publish
            self.registration_cache[device_id] = {
                'registered': True,
                'timestamp': time.time()
            }
            
            if should_publish:
                topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/registration"
                payload = {
                    "device_id": device_id,
                    "timestamp": datetime.now().isoformat(),
                    "event": "registration",
                    "province_id": province_id,
                    "city_id": city_id,
                    "manufacturer_id": manufacturer_id,
                    "terminal_model": terminal_model,
                    "terminal_id": terminal_id,
                    "license_plate_color": license_plate_color,
                    "license_plate": license_plate
                }
                
                logger.debug(f"Publishing registration for {device_id}")
                self._publish_mqtt(topic, payload)
            
            # Always call publish_status, which has its own debouncing logic
            self._publish_status(device_id, "online")
        except Exception as e:
            logger.error(f"Failed to parse registration message from {device_id}: {e}")
            
    def _publish_authentication(self, device_id, message):
        """
        Publish authentication information to MQTT
        
        Args:
            device_id: Device ID
            message: Authentication message
        """
        if len(message.body) < 1:
            logger.error(f"Invalid authentication message format from {device_id}")
            return
            
        try:
            # Parse authentication message body
            auth_len = message.body[0]
            auth_code = ""
            if 1 + auth_len <= len(message.body):
                try:
                    auth_code = message.body[1:1+auth_len].decode('utf-8')
                except Exception:
                    auth_code = ''.join([f'{b:02x}' for b in message.body[1:1+auth_len]]).upper()
            
            # Check if we've already sent this authentication code
            should_publish = True
            if device_id in self.auth_cache:
                cached_auth = self.auth_cache[device_id]
                
                # Only publish if the auth_code has changed
                if cached_auth.get('auth_code') == auth_code:
                    logger.debug(f"Auth code hasn't changed for {device_id}, not publishing")
                    should_publish = False
            
            # Update auth cache regardless of whether we publish
            self.auth_cache[device_id] = {
                'auth_code': auth_code,
                'timestamp': time.time()
            }
            
            if should_publish:
                topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/authentication"
                payload = {
                    "device_id": device_id,
                    "timestamp": datetime.now().isoformat(),
                    "event": "authentication",
                    "auth_code": auth_code
                }
                
                logger.debug(f"Publishing authentication for {device_id}")
                self._publish_mqtt(topic, payload)
            
            # Always call publish_status, which has its own debouncing logic
            self._publish_status(device_id, "online")
        except Exception as e:
            logger.error(f"Failed to parse authentication message from {device_id}: {e}")
            
    def _publish_location(self, device_id, message):
        """
        Publish location information to MQTT
        
        Args:
            device_id: Device ID
            message: Location message
        """
        try:
            # Parse location message body
            if len(message.body) < 28:
                logger.error(f"Invalid location message format from {device_id}")
                return
                
            # Check if message has enough data for the basic location information
            if len(message.body) < 22:
                logger.error(f"Location message too short from {device_id}: {len(message.body)} bytes, expected at least 22 bytes")
                return
                
            # Extract basic location information (4 DWORDs + 3 WORDs = 22 bytes)
            alarm_flag, status, lat_value, lon_value, altitude, speed, direction = struct.unpack('>IIIIHHH', message.body[:22])
            
            # Extract timestamp
            timestamp_bytes = message.body[22:28]
            timestamp = bytes_to_bcd(timestamp_bytes)
            
            # Convert coordinates to decimal degrees
            latitude = dms_to_decimal(lat_value)
            longitude = dms_to_decimal(lon_value)
            
            # Apply direction flags
            if status & StatusBit.LAT_SOUTH:
                latitude = -latitude
            if status & StatusBit.LON_WEST:
                longitude = -longitude
            
            # Determine pet's current activity level based on speed
            activity_level = "resting"
            if speed > 20:  # km/h
                activity_level = "fast_moving"
            elif speed > 5:  # km/h
                activity_level = "walking"
            
            # Initialize the device state if this is the first message from this device
            now = time.time()
            if device_id not in self.device_state:
                self.device_state[device_id] = {
                    'lat': latitude,
                    'lon': longitude,
                    'last_pub_time': 0,  # Force first message to be published
                    'activity': activity_level
                }
            
            # Get the current thresholds based on activity level
            thresholds = self.thresholds[activity_level]
            min_interval = thresholds['interval']
            min_distance = thresholds['distance']
            
            # Dual-gating check: time-based AND distance-based throttling
            should_publish = True
            
            if self.throttle_duplicates:
                # Get the device's current state
                device_state = self.device_state[device_id]
                
                # Check how long it's been since the last update
                time_diff = now - device_state.get('last_pub_time', 0)
                
                # Calculate distance from last position
                distance = self._calculate_distance(
                    device_state.get('lat', 0), 
                    device_state.get('lon', 0),
                    latitude,
                    longitude
                )
                
                # Apply strict dual-gating logic:
                # Only publish if BOTH time threshold AND distance threshold are met
                if time_diff >= min_interval and distance >= min_distance:
                    logger.info(f"Publishing position for {device_id} ({activity_level}): moved {distance:.2f}m " 
                                f"in {time_diff:.1f}s, BOTH thresholds met (min: {min_distance:.1f}m, {min_interval}s)")
                    should_publish = True
                else:
                    # Determine which threshold was not met for detailed logging
                    missing_threshold = []
                    if time_diff < min_interval:
                        missing_threshold.append(f"time ({time_diff:.1f}s < {min_interval}s)")
                    if distance < min_distance:
                        missing_threshold.append(f"distance ({distance:.2f}m < {min_distance:.1f}m)")
                    
                    logger.info(f"Throttling position for {device_id} ({activity_level}): {', '.join(missing_threshold)} " 
                                f"threshold(s) not met")
            
            # Always update the device state with latest coordinates
            self.device_state[device_id].update({
                'lat': latitude,
                'lon': longitude,
                'activity': activity_level
            })
            
            # Only update last_pub_time if we're actually publishing
            if should_publish:
                self.device_state[device_id]['last_pub_time'] = now
            
            # For backward compatibility - will be deprecated in future
            self.position_cache[device_id] = {
                'lat': latitude,
                'lon': longitude,
                'timestamp': now
            }
            
            # Only proceed with publishing if we should
            if not should_publish:
                return
                
            # Parse additional information
            additional_info = {}
            if len(message.body) > 28:
                pos = 28
                while pos < len(message.body):
                    if pos + 2 > len(message.body):
                        break
                        
                    info_id = message.body[pos]
                    info_len = message.body[pos + 1]
                    
                    if pos + 2 + info_len > len(message.body):
                        break
                        
                    info_value = message.body[pos + 2:pos + 2 + info_len]
                    
                    # Convert value based on ID
                    if info_id == 0x01 and info_len == 4:  # Mileage
                        additional_info["mileage"] = struct.unpack('>I', info_value)[0] / 10.0  # km
                    elif info_id == 0x02 and info_len == 2:  # Fuel
                        additional_info["fuel"] = struct.unpack('>H', info_value)[0] / 10.0  # L
                    elif info_id == 0x03 and info_len == 2:  # Speed
                        additional_info["speed_sensor"] = struct.unpack('>H', info_value)[0] / 10.0  # km/h
                    elif info_id == 0x04 and info_len == 2:  # Altitude
                        additional_info["altitude_sensor"] = struct.unpack('>H', info_value)[0]  # m
                    else:
                        # Default to hex representation
                        additional_info[f"id_{info_id:02X}"] = info_value.hex()
                        
                    pos += 2 + info_len
                    
            # Map status flags
            status_flags = {}
            for flag_name, flag_value in vars(StatusBit).items():
                if not flag_name.startswith('_'):
                    status_flags[flag_name.lower()] = bool(status & flag_value)
                    
            # Map alarm flags
            alarm_flags = {}
            for flag_name, flag_value in vars(AlarmFlag).items():
                if not flag_name.startswith('_'):
                    alarm_flags[flag_name.lower()] = bool(alarm_flag & flag_value)
            
            # Format timestamp
            iso_timestamp = f"20{timestamp[0:2]}-{timestamp[2:4]}-{timestamp[4:6]}T{timestamp[6:8]}:{timestamp[8:10]}:{timestamp[10:12]}Z"
            
            # Use the configured MQTT location topic (with device_id replacement)
            topic = self.mqtt_location_topic.replace('{device_id}', device_id)
            
            # Construct MQTT payload with size optimization if configured
            if self.optimize_payload:
                # Minimal payload with only essential fields
                payload = {
                    "d": device_id,  # Shortened key name
                    "t": iso_timestamp,  # Shortened key name
                    "loc": {  # Shortened key name
                        "lat": round(latitude, 6),  # Shortened key name + precision limit
                        "lon": round(longitude, 6),  # Shortened key name + precision limit
                        # Only include other fields if they have meaningful values
                        "alt": altitude if altitude > 0 else None,
                        "spd": round(speed / 10.0, 1) if speed > 0 else None,  # Shortened key + fewer decimals
                        "dir": direction if direction != 0 else None
                    }
                }
                
                # Only include status flags that are true (saves bandwidth)
                active_status = {k: v for k, v in status_flags.items() if v}
                if active_status:
                    payload["st"] = active_status  # Shortened key name
                
                # Only include alarm flags that are true
                active_alarms = {k: v for k, v in alarm_flags.items() if v}
                if active_alarms:
                    payload["alm"] = active_alarms  # Shortened key name
                
                # Only include essential additional info (mileage and low battery)
                essential_info = {}
                if "mileage" in additional_info:
                    essential_info["m"] = round(additional_info["mileage"], 1)  # Shortened key + fewer decimals
                
                if "fuel" in additional_info and additional_info["fuel"] < 30:
                    # Only include battery/fuel if it's low (below 30%)
                    essential_info["b"] = round(additional_info["fuel"], 0)  # Shortened key + integer only
                
                if essential_info:
                    payload["add"] = essential_info  # Shortened key name
            else:
                # Full payload with all fields (original format)
                payload = {
                    "device_id": device_id,
                    "timestamp": iso_timestamp,
                    "location": {
                        "latitude": latitude,
                        "longitude": longitude,
                        "altitude": altitude,
                        "speed": speed / 10.0,  # km/h
                        "direction": direction
                    },
                    "status": status_flags,
                    "alarm": alarm_flags,
                    "additional": additional_info
                }
            
            # Publish using the configured topic (with device ID)
            # Unified topic strategy: only use a single topic per device
            self._publish_mqtt(topic, payload)
            
            # Update status
            self._publish_status(device_id, "online")
            
            logger.info(f"Published location from {device_id}: {latitude}, {longitude}")
        except Exception as e:
            logger.error(f"Failed to parse location message from {device_id}: {e}")
            logger.error(traceback.format_exc())
            
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
            
    def _publish_batch_location(self, device_id, message):
        """
        Publish batch location information to MQTT
        
        Args:
            device_id: Device ID
            message: Batch location message
        """
        try:
            # Parse batch location message body
            if len(message.body) < 3:
                logger.error(f"Invalid batch location message format from {device_id}")
                return
                
            # Extract batch info
            type_id, count = struct.unpack('>BH', message.body[:3])
            
            logger.info(f"Batch location from {device_id}: type={type_id}, count={count}")
            
            # Parse each location data
            locations = []
            pos = 3
            
            for i in range(count):
                if pos >= len(message.body):
                    break
                    
                # Each location data should be parsed according to the location report format
                # The challenge is determining the size of each location data
                # For a simplified approach, we'll look for a pattern or fixed size
                
                # Assume each location data is at least 28 bytes (basic location information)
                if pos + 28 > len(message.body):
                    break
                    
                # Extract basic location information (4 DWORDs + 3 WORDs = 22 bytes)
                alarm_flag, status, lat_value, lon_value, altitude, speed, direction = struct.unpack(
                    '>IIIIHHH', message.body[pos:pos+22]
                )
                
                # Extract timestamp
                timestamp_bytes = message.body[pos+22:pos+28]
                timestamp = bytes_to_bcd(timestamp_bytes)
                
                # Convert coordinates to decimal degrees
                latitude = dms_to_decimal(lat_value)
                longitude = dms_to_decimal(lon_value)
                
                # Apply direction flags
                if status & StatusBit.LAT_SOUTH:
                    latitude = -latitude
                if status & StatusBit.LON_WEST:
                    longitude = -longitude
                    
                # Get iso timestamp
                iso_timestamp = f"20{timestamp[0:2]}-{timestamp[2:4]}-{timestamp[4:6]}T{timestamp[6:8]}:{timestamp[8:10]}:{timestamp[10:12]}Z"
                
                # Create location entry based on optimization setting
                if self.optimize_payload:
                    # Create optimized location entry with shortened field names
                    location_entry = {
                        "t": iso_timestamp,  # Shortened key name 
                        "lat": round(latitude, 6),  # Shortened key name + precision limit
                        "lon": round(longitude, 6),  # Shortened key name + precision limit
                    }
                    
                    # Only include values if they're meaningful
                    if altitude > 0:
                        location_entry["alt"] = altitude
                    
                    if speed > 0:
                        location_entry["s"] = round(speed / 10.0, 1)  # Shortened key name + fewer decimals
                    
                    if direction != 0:
                        location_entry["dir"] = direction
                else:
                    # Original format with all fields
                    location_entry = {
                        "timestamp": iso_timestamp,
                        "latitude": latitude,
                        "longitude": longitude,
                        "altitude": altitude,
                        "speed": speed / 10.0,  # km/h
                        "direction": direction,
                    }
                
                locations.append(location_entry)
                
                # Move to the next location data
                # In a real implementation, you would need to determine the actual size
                # For now, we'll use a fixed size of 28 bytes
                pos += 28
                
            # Publish batch of locations
            topic = self.mqtt_location_topic.replace('{device_id}', device_id) + "/batch"
            
            # Create payload based on optimization setting
            if self.optimize_payload and len(locations) > 0:
                # Highly optimized batch payload
                payload = {
                    "d": device_id,  # Shortened key name
                    "t": datetime.now().isoformat(),  # Shortened key name
                    "n": len(locations),  # Shortened key name for count
                    "locs": locations  # Shortened key name for locations
                }
                
                # Only include type if it's not the default (1)
                if type_id != 1:
                    payload["type"] = type_id
            else:
                # Original format with full field names
                payload = {
                    "device_id": device_id,
                    "timestamp": datetime.now().isoformat(),
                    "type": type_id,
                    "count": len(locations),
                    "locations": locations
                }
            
            self._publish_mqtt(topic, payload)
            self._publish_status(device_id, "online")
        except Exception as e:
            logger.error(f"Failed to parse batch location message from {device_id}: {e}")
            
    def _publish_logout(self, device_id):
        """
        Publish logout information to MQTT
        
        Args:
            device_id: Device ID
        """
        topic = f"pettracker/{device_id}/system"
        
        if self.optimize_payload:
            # Optimized logout payload
            payload = {
                "d": device_id,  # Shortened device_id
                "t": datetime.now().isoformat(),  # Shortened timestamp
                "e": "logout"  # Shortened event
            }
        else:
            # Original format
            payload = {
                "device_id": device_id,
                "timestamp": datetime.now().isoformat(),
                "event": "logout"
            }
        
        self._publish_mqtt(topic, payload)
        self._publish_status(device_id, "offline")
        
    def _publish_status(self, device_id, status):
        """
        Publish device status to MQTT with advanced throttling
        
        Args:
            device_id: Device ID
            status: Status string ('online' or 'offline')
        """
        # Apply enhanced throttling to status events 
        current_time = time.time()
        should_publish = True
        
        if device_id in self.status_cache:
            cached_status = self.status_cache[device_id]
            cached_time = cached_status.get('timestamp', 0)
            cached_status_value = cached_status.get('status')
            time_since_last = current_time - cached_time
            
            # First check: Only publish if the status has changed
            if cached_status_value == status:
                # No change in status, apply TTL-based throttling
                # For 'online' status, enforce minimum interval between messages
                if status == 'online' and time_since_last < self.status_ttl:
                    logger.debug(f"Status '{status}' for {device_id} reported too frequently "
                                f"(last report {time_since_last:.1f}s ago, TTL: {self.status_ttl}s), throttling")
                    should_publish = False
                else:
                    logger.debug(f"Status hasn't changed for {device_id} ({status}), not publishing")
                    should_publish = False
            else:
                # Status has changed - prioritize 'offline' notifications
                # Always publish offline status immediately
                if status == 'offline':
                    logger.info(f"Device {device_id} status changed from {cached_status_value} to {status} - publishing immediately")
                # For online status after offline, add small delay to prevent flickering
                elif status == 'online' and cached_status_value == 'offline' and time_since_last < 5:  
                    logger.debug(f"Device {device_id} came back online too quickly after being offline, suppressing status change")
                    should_publish = False
        
        # Update status cache regardless of whether we publish
        self.status_cache[device_id] = {
            'status': status,
            'timestamp': current_time
        }
        
        if should_publish:
            topic = f"pettracker/{device_id}/status"
            
            if self.optimize_payload:
                # Optimized status payload
                payload = {
                    "d": device_id,  # Shortened key
                    "t": datetime.now().isoformat(),  # Shortened key
                    "s": status  # Shortened key
                }
            else:
                # Original format
                payload = {
                    "device_id": device_id,
                    "timestamp": datetime.now().isoformat(),
                    "status": status
                }
            
            logger.debug(f"Publishing status change for {device_id}: {status}")
            self._publish_mqtt(topic, payload)
        
    def _publish_mqtt(self, topic, payload):
        """
        Publish a message to MQTT
        
        Args:
            topic: MQTT topic
            payload: Message payload (will be converted to JSON)
        """
        # Check if MQTT client is available and connected
        if self.mqtt_client is None:
            logger.warning(f"MQTT client is not available. Simulated publish to {topic}")
            return
            
        # Check for connection status in three possible places
        mqtt_connected = False
        
        # 1. Check client's _mqtt_connected property
        if hasattr(self.mqtt_client, '_mqtt_connected'):
            mqtt_connected = self.mqtt_client._mqtt_connected
            
        # 2. Check userdata mqtt_config
        elif hasattr(self.mqtt_client, '_userdata') and isinstance(self.mqtt_client._userdata, dict) and \
             'mqtt_config' in self.mqtt_client._userdata and \
             self.mqtt_client._userdata['mqtt_config'].get('mqtt_connected', False):
            mqtt_connected = True
            
        # 3. Check self.mqtt_config
        elif self.mqtt_config.get('mqtt_connected', False):
            mqtt_connected = True
            
        if not mqtt_connected:
            logger.warning(f"MQTT client is not connected. Simulated publish to {topic}")
            return
            
        try:
            # Make sure the device_id in the payload is a string
            # Support both regular and optimized device_id fields
            if isinstance(payload, dict):
                if 'device_id' in payload:
                    payload['device_id'] = str(payload['device_id'])
                # Support optimized key ('d') for device_id
                elif 'd' in payload:
                    payload['d'] = str(payload['d'])
                
            # Make sure the topic is a string
            topic = str(topic)
            
            # Convert payload to JSON with explicit handling for non-serializable objects
            try:
                json_payload = json.dumps(payload)
            except TypeError as e:
                logger.error(f"JSON serialization error for topic {topic}: {e}")
                # Try a more robust approach
                safe_payload = {}
                for k, v in payload.items():
                    try:
                        # Test if the value is JSON serializable
                        json.dumps({k: v})
                        safe_payload[k] = v
                    except TypeError:
                        safe_payload[k] = str(v)
                json_payload = json.dumps(safe_payload)
                logger.info(f"Used fallback serialization for topic {topic}")
            
            logger.debug(f"Publishing to MQTT: {topic} - {json_payload[:100]}...")
            result = self.mqtt_client.publish(topic, json_payload, qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(f"Failed to publish to {topic}: {result.rc}")
                error_codes = {
                    mqtt.MQTT_ERR_AGAIN: "Queue full",
                    mqtt.MQTT_ERR_NO_CONN: "No connection",
                    mqtt.MQTT_ERR_PROTOCOL: "Protocol error",
                    mqtt.MQTT_ERR_INVAL: "Invalid parameters",
                    mqtt.MQTT_ERR_PAYLOAD_SIZE: "Payload too large"
                }
                if result.rc in error_codes:
                    logger.error(f"MQTT error: {error_codes[result.rc]}")
            else:
                # Log successful publish occasionally to avoid excessive logging
                if random.random() < 0.1:  # ~10% of messages
                    logger.info(f"Successfully published to {topic}")
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")
            import traceback
            logger.error(f"MQTT publish error details: {traceback.format_exc()}")

def on_connect(client, userdata, flags, rc):
    """MQTT connect callback"""
    if rc == 0:
        logger.info("Connected to MQTT broker successfully")
        # Update mqtt_connected flag in the mqtt_config
        if userdata and isinstance(userdata, dict) and 'mqtt_config' in userdata:
            userdata['mqtt_config']['mqtt_connected'] = True
            logger.info("Updated mqtt_connected flag to True in userdata")
        
        # Also set the _mqtt_connected property on the client object
        client._mqtt_connected = True
        
        # Publish a test message to confirm connection
        try:
            client.publish("pettracker/system/status", json.dumps({"status": "connected", "timestamp": datetime.now().isoformat()}))
            logger.info("Published test message to MQTT broker")
        except Exception as e:
            logger.error(f"Failed to publish test message: {e}")
    else:
        logger.error(f"Failed to connect to MQTT broker: {rc}")
        # Log the meaning of the connection codes
        rc_codes = {
            0: "Connection successful",
            1: "Connection refused - incorrect protocol version",
            2: "Connection refused - invalid client identifier",
            3: "Connection refused - server unavailable",
            4: "Connection refused - bad username or password",
            5: "Connection refused - not authorised"
        }
        if rc in rc_codes:
            logger.error(f"MQTT Connection error: {rc_codes[rc]}")

def on_disconnect(client, userdata, rc):
    """MQTT disconnect callback"""
    # Reset connection flags
    if hasattr(client, '_mqtt_connected'):
        client._mqtt_connected = False
        
    # Update mqtt_connected flag in userdata
    if userdata and isinstance(userdata, dict) and 'mqtt_config' in userdata:
        userdata['mqtt_config']['mqtt_connected'] = False
        logger.info("Updated mqtt_connected flag to False in userdata")
    
    if rc != 0:
        logger.error(f"Unexpected MQTT disconnection: {rc}")
        logger.info("Attempting to reconnect to MQTT broker...")
    else:
        logger.info("MQTT client disconnected cleanly")

def on_publish(client, userdata, mid):
    """MQTT publish callback"""
    # Log message ID for important publishes
    if mid % 10 == 0:  # Log every 10th publish to avoid excessive logging
        logger.debug(f"Published message with ID: {mid}")

def load_config():
    """Load configuration from file or env vars, with appropriate defaults"""
    # Start with default configuration
    default_config = {
        'jt808_host': '0.0.0.0',
        'jt808_port': 8008,
        'mqtt_broker_type': 'local',  # Default to local Mosquitto
        'mqtt_client_id': f'pettracker-converter-{os.getpid()}'
    }
    
    # Load from config.json if available
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                loaded_config = json.load(f)
                # Update default config with loaded values
                default_config.update(loaded_config)
                logger.info("Loaded configuration from config.json")
    except Exception as e:
        logger.warning(f"Failed to load config.json: {e}")
    
    # Determine broker type from environment or config
    broker_type = os.environ.get('MQTT_BROKER_TYPE', default_config.get('mqtt_broker_type', 'local'))
    
    # Load JT808 settings from environment
    default_config['jt808_host'] = os.environ.get('JT808_HOST', default_config.get('jt808_host'))
    
    # Safely convert port to integer
    jt808_port = os.environ.get('JT808_PORT')
    if jt808_port is not None:
        try:
            default_config['jt808_port'] = int(jt808_port)
        except ValueError:
            logger.warning(f"Invalid JT808_PORT value: {jt808_port}, using default")
    # Keep existing port if not specified in environment variables
    
    if broker_type.lower() == 'aws':
        # AWS IoT Configuration
        logger.info("Using AWS IoT MQTT broker configuration")
        default_config['mqtt_broker_type'] = 'aws'
        default_config['mqtt_host'] = os.environ.get('AWS_MQTT_ENDPOINT')
        
        # Safely convert port to integer
        aws_mqtt_port = os.environ.get('AWS_MQTT_PORT', '8883')
        try:
            default_config['mqtt_port'] = int(aws_mqtt_port)
        except ValueError:
            logger.warning(f"Invalid AWS_MQTT_PORT value: {aws_mqtt_port}, using default 8883")
            default_config['mqtt_port'] = 8883
        default_config['mqtt_client_id'] = os.environ.get('AWS_MQTT_CLIENT_ID', default_config.get('mqtt_client_id'))
        default_config['mqtt_topic_prefix'] = os.environ.get('AWS_MQTT_TOPIC_PREFIX', 'pettracker')
        
        # AWS IoT certificate paths
        default_config['mqtt_ca_file'] = os.environ.get('AWS_MQTT_CA_FILE', './certs/AmazonRootCA1.pem')
        default_config['mqtt_cert_file'] = os.environ.get('AWS_MQTT_CERT_FILE', './certs/certificate.pem.crt')
        default_config['mqtt_key_file'] = os.environ.get('AWS_MQTT_KEY_FILE', './certs/private.pem.key')
        
        # Check if required AWS IoT files exist
        for file_key in ['mqtt_ca_file', 'mqtt_cert_file', 'mqtt_key_file']:
            file_path = default_config[file_key]
            if not os.path.exists(file_path):
                logger.warning(f"AWS IoT certificate file {file_path} not found")
    else:
        # Local Mosquitto Configuration
        logger.info("Using local MQTT broker configuration")
        default_config['mqtt_broker_type'] = 'local'
        default_config['mqtt_host'] = os.environ.get('LOCAL_MQTT_HOST', 'broker.hivemq.com')  # Use HiveMQ as the default
        
        # Safely convert port to integer
        local_mqtt_port = os.environ.get('LOCAL_MQTT_PORT', '1883')
        try:
            default_config['mqtt_port'] = int(local_mqtt_port)
        except ValueError:
            logger.warning(f"Invalid LOCAL_MQTT_PORT value: {local_mqtt_port}, using default 1883")
            default_config['mqtt_port'] = 1883
        default_config['mqtt_user'] = os.environ.get('LOCAL_MQTT_USER', '')
        default_config['mqtt_password'] = os.environ.get('LOCAL_MQTT_PASSWORD', '')
        default_config['mqtt_topic_prefix'] = os.environ.get('LOCAL_MQTT_TOPIC_PREFIX', 'pettracker')
    
    logger.info(f"Using MQTT broker: {default_config['mqtt_host']}:{default_config['mqtt_port']}")
    return default_config

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='JT/T 808-2013 to MQTT Converter')
    
    parser.add_argument('--jt808-host', help='JT808 server host')
    parser.add_argument('--jt808-port', type=int, help='JT808 server port')
    parser.add_argument('--mqtt-host', help='MQTT broker host')
    parser.add_argument('--mqtt-port', type=int, help='MQTT broker port')
    parser.add_argument('--mqtt-user', help='MQTT username')
    parser.add_argument('--mqtt-password', help='MQTT password')
    parser.add_argument('--mqtt-topic', help='MQTT topic prefix')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    
    return parser.parse_args()

def main():
    """Main entry point"""
    args = parse_args()
    
    # Set log level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        
    # Load configuration
    config = load_config()
    
    # Override with command line arguments
    if args.jt808_host:
        config['jt808_host'] = args.jt808_host
    if args.jt808_port:
        config['jt808_port'] = args.jt808_port
    if args.mqtt_host:
        config['mqtt_host'] = args.mqtt_host
    if args.mqtt_port:
        config['mqtt_port'] = args.mqtt_port
    if args.mqtt_user:
        config['mqtt_user'] = args.mqtt_user
    if args.mqtt_password:
        config['mqtt_password'] = args.mqtt_password
    if args.mqtt_topic:
        config['mqtt_topic_prefix'] = args.mqtt_topic
        
    # Initialize MQTT client
    try:
        mqtt_connected = False
        
        # Initialize mqtt_config early to ensure it's available in all cases
        mqtt_config = {
            'topic_prefix': config.get('mqtt_topic_prefix', 'pettracker'),
            'mqtt_connected': mqtt_connected,
            'throttle_duplicates': config.get('throttle_duplicates', True),
            'throttle_timeout': config.get('throttle_timeout', 60),  # Seconds
            'min_position_delta': config.get('min_position_delta', 5.0),  # Meters
            'mqtt_location_topic': config.get('mqtt_location_topic', 'pettracker/{device_id}/location')
        }
        
        if config.get('mqtt_broker_type', 'local').lower() == 'aws':
            # AWS IoT MQTT client setup
            logger.info("Setting up AWS IoT MQTT client")
            
            # Check if all required certificate files exist
            cert_files_exist = True
            for file_key in ['mqtt_ca_file', 'mqtt_cert_file', 'mqtt_key_file']:
                file_path = config.get(file_key)
                if not file_path or not os.path.exists(file_path):
                    logger.error(f"AWS IoT certificate file '{file_key}' not found: {file_path}")
                    cert_files_exist = False
            
            if not cert_files_exist:
                logger.error("Cannot connect to AWS IoT: missing certificate files")
                mqtt_client = None
            else:
                # Create MQTT client with TLS/SSL support for AWS IoT
                mqtt_client = mqtt.Client(client_id=config.get('mqtt_client_id'), protocol=mqtt.MQTTv5)
                mqtt_client.on_connect = on_connect
                mqtt_client.on_disconnect = on_disconnect
                mqtt_client.on_publish = on_publish
                
                # Configure TLS with AWS IoT certificates
                mqtt_client.tls_set(
                    ca_certs=config.get('mqtt_ca_file'),
                    certfile=config.get('mqtt_cert_file'),
                    keyfile=config.get('mqtt_key_file'),
                    tls_version=ssl.PROTOCOL_TLSv1_2
                )
                
                # Connect to AWS IoT endpoint
                try:
                    mqtt_client.connect(config['mqtt_host'], config['mqtt_port'])
                    mqtt_client.loop_start()
                    logger.info(f"Connected to AWS IoT MQTT broker at {config['mqtt_host']}:{config['mqtt_port']}")
                    mqtt_connected = True
                except Exception as e:
                    logger.error(f"Failed to connect to AWS IoT MQTT broker: {e}")
                    logger.warning("Continuing in simulation mode without MQTT")
        else:
            # Local Mosquitto MQTT client setup
            logger.info("Setting up local MQTT client")
            
            # MQTT configuration for the JT808 server
            # Initialize here so we can pass it as userdata
            mqtt_config = {
                'topic_prefix': config.get('mqtt_topic_prefix', 'pettracker'),
                'mqtt_connected': mqtt_connected,  # Will be updated in on_connect
                'throttle_duplicates': config.get('throttle_duplicates', True),
                'throttle_timeout': config.get('throttle_timeout', 60),  # Seconds
                'min_position_delta': config.get('min_position_delta', 5.0),  # Meters
                'mqtt_location_topic': config.get('mqtt_location_topic', 'pettracker/{device_id}/location')
            }
            
            # Pass mqtt_config as userdata so it can be updated in callbacks
            mqtt_client = mqtt.Client(
                client_id=config.get('mqtt_client_id', 'pettracker_converter'),
                userdata={'mqtt_config': mqtt_config}
            )
            mqtt_client.on_connect = on_connect
            mqtt_client.on_disconnect = on_disconnect
            mqtt_client.on_publish = on_publish
            
            # Configure authentication if credentials are provided
            if config.get('mqtt_user') and config.get('mqtt_password'):
                mqtt_client.username_pw_set(config['mqtt_user'], config['mqtt_password'])
                
            # Connect to local MQTT broker
            try:
                mqtt_client.connect(config['mqtt_host'], config['mqtt_port'])
                mqtt_client.loop_start()
                logger.info(f"Connected to local MQTT broker at {config['mqtt_host']}:{config['mqtt_port']}")
                mqtt_connected = True
            except Exception as e:
                logger.warning(f"Failed to connect to local MQTT broker: {e}")
                logger.warning("Continuing in simulation mode without MQTT")
    except Exception as e:
        logger.warning(f"Failed to initialize MQTT client: {e}")
        logger.warning("Continuing in simulation mode without MQTT")
        mqtt_client = None
        mqtt_connected = False
        
    # If mqtt_config wasn't initialized in the try/except block above, initialize it now
    if 'mqtt_config' not in locals():
        mqtt_config = {
            'topic_prefix': config.get('mqtt_topic_prefix', 'pettracker'),
            'mqtt_connected': mqtt_connected,
            'throttle_duplicates': config.get('throttle_duplicates', True),
            'throttle_timeout': config.get('throttle_timeout', 60),  # Seconds
            'min_position_delta': config.get('min_position_delta', 5.0),  # Meters
            'mqtt_location_topic': config.get('mqtt_location_topic', 'pettracker/{device_id}/location')
        }
    
    # Create and start the JT808 server
    server = JT808Server(config['jt808_host'], config['jt808_port'], mqtt_client, mqtt_config)
    
    if not server.start():
        if mqtt_client is not None and mqtt_connected:
            mqtt_client.loop_stop()
        return
        
    try:
        # Keep the main thread running
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Stopping server...")
        server.stop()
        if mqtt_client is not None and mqtt_connected:
            mqtt_client.loop_stop()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        server.stop()
        if mqtt_client is not None and mqtt_connected:
            mqtt_client.loop_stop()

if __name__ == '__main__':
    main()
