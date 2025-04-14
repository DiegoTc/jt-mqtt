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
    import paho.mqtt.client as mqtt
    from datetime import datetime
    
    # Configure basic logging before importing modules that might use it
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('jt808-converter')
    
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
        
        while self.running and client_socket in self.clients:
            try:
                # Receive data
                data = client_socket.recv(1024)
                if not data:
                    logger.info(f"Connection closed by client {self.clients[client_socket]['addr']}")
                    self._close_client(client_socket)
                    break
                    
                # Add to buffer
                buffer.extend(data)
                
                # Process complete messages in the buffer
                self._process_buffer(client_socket)
            except Exception as e:
                if self.running and client_socket in self.clients:
                    logger.error(f"Error handling client {self.clients[client_socket]['addr']}: {e}")
                    self._close_client(client_socket)
                break
                
    def _process_buffer(self, client_socket):
        """
        Process the client's buffer to extract complete messages
        
        Args:
            client_socket: Client socket
        """
        buffer = self.clients[client_socket]['buffer']
        
        while len(buffer) > 2:
            # Find start and end markers
            start_idx = buffer.find(b'\x7e')
            if start_idx == -1:
                buffer.clear()
                break
                
            # Remove any data before the start marker
            if start_idx > 0:
                buffer = buffer[start_idx:]
                self.clients[client_socket]['buffer'] = buffer
                
            # Find the end marker
            end_idx = buffer.find(b'\x7e', 1)
            if end_idx == -1:
                # No complete message yet
                break
                
            # Extract the complete message
            message_data = buffer[:end_idx+1]
            buffer = buffer[end_idx+1:]
            self.clients[client_socket]['buffer'] = buffer
            
            # Debug log the message data in detail
            logger.debug(f"Raw message data: {message_data}")
            logger.debug(f"Raw message data length: {len(message_data)} bytes")
            logger.debug(f"Raw message data hex: {message_data.hex()}")
            
            try:
                # Decode the message
                message = Message.decode(message_data)
                
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
                logger.error(f"Failed to decode message: {e}")
                logger.error(traceback.format_exc())
                
    def _process_message(self, client_socket, message):
        """
        Process a decoded message
        
        Args:
            client_socket: Client socket
            message: Decoded Message object
        """
        device_id = self.clients[client_socket]['device_id'] or 'unknown'
        logger.debug(f"Received message from {device_id}: {message.msg_id:04X}, length: {len(message.body)} bytes")
        
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
            logger.info(f"Authentication from {device_id}")
            self._send_general_response(client_socket, message, 0)
            self._publish_authentication(device_id, message)
            
        elif message.msg_id == MessageID.LOCATION_REPORT:
            logger.info(f"Location report from {device_id}")
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
            logger.info(f"Unsupported message type from {device_id}: {message.msg_id:04X}")
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
            response = Message.create_platform_general_response(
                message.phone_no, message.msg_serial_no, message.msg_id, result
            )
            
            client_socket.sendall(response.encode())
            logger.debug(f"Sent general response to {message.phone_no}: msg_id={message.msg_id:04X}, result={result}")
        except Exception as e:
            logger.error(f"Failed to send general response: {e}")
            
    def _send_registration_response(self, client_socket, message, result, auth_code):
        """
        Send a registration response to the client
        
        Args:
            client_socket: Client socket
            message: Original message
            result: Result code
            auth_code: Authentication code
        """
        try:
            # Prepare registration response body
            body = struct.pack('>HB', message.msg_serial_no, result)
            
            # Add auth code
            auth_bytes = auth_code.encode('utf-8')
            body += bytes([len(auth_bytes)]) + auth_bytes
            
            # Create response message
            response = Message(
                MessageID.TERMINAL_REGISTRATION_RESPONSE,
                message.phone_no,
                body
            )
            
            encoded_response = response.encode()
            logger.debug(f"Registration response body: {body.hex()}")
            logger.debug(f"Registration response encoded: {encoded_response.hex()}")
            
            client_socket.sendall(encoded_response)
            logger.debug(f"Sent registration response to {message.phone_no}: result={result}, auth_code={auth_code}")
        except Exception as e:
            logger.error(f"Failed to send registration response: {e}")
            
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
        topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/heartbeat"
        payload = {
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
            "event": "heartbeat"
        }
        
        self._publish_mqtt(topic, payload)
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
            
            self._publish_mqtt(topic, payload)
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
            
            topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/authentication"
            payload = {
                "device_id": device_id,
                "timestamp": datetime.now().isoformat(),
                "event": "authentication",
                "auth_code": auth_code
            }
            
            self._publish_mqtt(topic, payload)
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
                
            # Extract basic location information
            alarm_flag, status, lat_value, lon_value, altitude, speed, direction = struct.unpack('>IIIIHHB', message.body[:19])
            
            # Extract timestamp
            timestamp_bytes = message.body[19:25]
            timestamp = bytes_to_bcd(timestamp_bytes)
            
            # Convert coordinates to decimal degrees
            latitude = dms_to_decimal(lat_value)
            longitude = dms_to_decimal(lon_value)
            
            # Apply direction flags
            if status & StatusBit.LAT_SOUTH:
                latitude = -latitude
            if status & StatusBit.LON_WEST:
                longitude = -longitude
                
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
            
            # Construct MQTT payload
            topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/location"
            payload = {
                "device_id": device_id,
                "timestamp": f"20{timestamp[0:2]}-{timestamp[2:4]}-{timestamp[4:6]}T{timestamp[6:8]}:{timestamp[8:10]}:{timestamp[10:12]}Z",
                "event": "location",
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
            
            self._publish_mqtt(topic, payload)
            
            # Also publish to a special topic for real-time tracking
            tracking_topic = f"{self.mqtt_config['topic_prefix']}/tracking"
            tracking_payload = {
                "device_id": device_id,
                "timestamp": datetime.now().isoformat(),
                "latitude": latitude,
                "longitude": longitude,
                "speed": speed / 10.0,
                "direction": direction
            }
            self._publish_mqtt(tracking_topic, tracking_payload)
            
            # Update status
            self._publish_status(device_id, "online")
        except Exception as e:
            logger.error(f"Failed to parse location message from {device_id}: {e}")
            
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
                    
                # Extract basic location information
                alarm_flag, status, lat_value, lon_value, altitude, speed, direction = struct.unpack(
                    '>IIIIHHB', message.body[pos:pos+19]
                )
                
                # Extract timestamp
                timestamp_bytes = message.body[pos+19:pos+25]
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
                
                locations.append({
                    "timestamp": iso_timestamp,
                    "latitude": latitude,
                    "longitude": longitude,
                    "altitude": altitude,
                    "speed": speed / 10.0,  # km/h
                    "direction": direction,
                })
                
                # Move to the next location data
                # In a real implementation, you would need to determine the actual size
                # For now, we'll use a fixed size of 28 bytes
                pos += 28
                
            # Publish batch of locations
            topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/batch_location"
            payload = {
                "device_id": device_id,
                "timestamp": datetime.now().isoformat(),
                "event": "batch_location",
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
        topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/logout"
        payload = {
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
            "event": "logout"
        }
        
        self._publish_mqtt(topic, payload)
        self._publish_status(device_id, "offline")
        
    def _publish_status(self, device_id, status):
        """
        Publish device status to MQTT
        
        Args:
            device_id: Device ID
            status: Status string ('online' or 'offline')
        """
        topic = f"{self.mqtt_config['topic_prefix']}/{device_id}/status"
        payload = {
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
            "status": status
        }
        
        self._publish_mqtt(topic, payload)
        
    def _publish_mqtt(self, topic, payload):
        """
        Publish a message to MQTT
        
        Args:
            topic: MQTT topic
            payload: Message payload (will be converted to JSON)
        """
        # Check if MQTT client is available and connected
        if self.mqtt_client is None or not self.mqtt_config.get('mqtt_connected', False):
            logger.debug(f"Simulated MQTT publish to {topic}: {payload}")
            return
            
        try:
            # Make sure the device_id in the payload is a string
            if isinstance(payload, dict) and 'device_id' in payload:
                payload['device_id'] = str(payload['device_id'])
                
            # Make sure the topic is a string
            topic = str(topic)
            
            result = self.mqtt_client.publish(topic, json.dumps(payload), qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(f"Failed to publish to {topic}: {result}")
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")

def on_connect(client, userdata, flags, rc):
    """MQTT connect callback"""
    if rc == 0:
        logger.info("Connected to MQTT broker")
    else:
        logger.error(f"Failed to connect to MQTT broker: {rc}")

def on_disconnect(client, userdata, rc):
    """MQTT disconnect callback"""
    if rc != 0:
        logger.error(f"Unexpected MQTT disconnection: {rc}")

def on_publish(client, userdata, mid):
    """MQTT publish callback"""
    pass  # Can be used for QoS tracking

def load_config():
    """Load configuration from file or use defaults"""
    default_config = {
        'jt808_host': '0.0.0.0',
        'jt808_port': 8008,  # Updated to match config.json
        'mqtt_host': 'localhost',
        'mqtt_port': 1883,
        'mqtt_user': '',
        'mqtt_password': '',
        'mqtt_topic_prefix': 'jt808',
        'mqtt_client_id': f'jt808-converter-{os.getpid()}'
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
        mqtt_client = mqtt.Client(client_id=config.get('mqtt_client_id', 'jt808_converter'))
        mqtt_client.on_connect = on_connect
        mqtt_client.on_disconnect = on_disconnect
        mqtt_client.on_publish = on_publish
        
        if config.get('mqtt_user') and config.get('mqtt_password'):
            mqtt_client.username_pw_set(config['mqtt_user'], config['mqtt_password'])
            
        # Connect to MQTT broker
        try:
            mqtt_client.connect(config['mqtt_host'], config['mqtt_port'])
            mqtt_client.loop_start()
            logger.info(f"Connected to MQTT broker at {config['mqtt_host']}:{config['mqtt_port']}")
            mqtt_connected = True
        except Exception as e:
            logger.warning(f"Failed to connect to MQTT broker: {e}")
            logger.warning("Continuing in simulation mode without MQTT")
            mqtt_connected = False
    except Exception as e:
        logger.warning(f"Failed to initialize MQTT client: {e}")
        logger.warning("Continuing in simulation mode without MQTT")
        mqtt_client = None
        mqtt_connected = False
        
    # MQTT configuration for the JT808 server
    mqtt_config = {
        'topic_prefix': config.get('mqtt_topic_prefix', 'jt808'),
        'mqtt_connected': mqtt_connected
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
