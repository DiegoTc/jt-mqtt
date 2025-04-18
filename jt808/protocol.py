"""
JT/T 808-2013 Protocol Implementation
"""
import socket
import struct
import time
import logging
import threading
import queue
from jt808.message import Message
from jt808.constants import MessageID, ResultCode
from jt808.utils import calculate_checksum, apply_escape_rules, remove_escape_rules

class JT808Protocol:
    """
    JT/T 808-2013 Protocol handler
    
    Handles communication according to the JT/T 808-2013 protocol.
    """
    def __init__(self, device_id, server_ip, server_port, logger=None):
        """
        Initialize the protocol handler
        
        Args:
            device_id: Device ID (phone number) for the terminal
            server_ip: Server IP address
            server_port: Server port
            logger: Logger instance (optional)
        """
        self.device_id = str(device_id)
        self.server_ip = server_ip
        self.server_port = server_port
        self.socket = None
        self.connected = False
        self.authenticated = False
        self.logger = logger or logging.getLogger('jt808')
        self.msg_serial_no = 0
        self.recv_queue = queue.Queue()
        self.recv_thread = None
        self.auth_code = None
        
    def connect(self):
        """Connect to the server"""
        if self.connected:
            return
            
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.server_ip, self.server_port))
            self.connected = True
            self.logger.info(f"Connected to {self.server_ip}:{self.server_port}")
            
            # Start the receive thread
            self.recv_thread = threading.Thread(target=self._receive_thread)
            self.recv_thread.daemon = True
            self.recv_thread.start()
            
            return True
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            return False
            
    def disconnect(self):
        """Disconnect from the server"""
        if not self.connected:
            return
            
        try:
            self.connected = False
            self.authenticated = False
            if self.socket:
                self.socket.close()
            self.logger.info("Disconnected from server")
        except Exception as e:
            self.logger.error(f"Disconnection error: {e}")
            
    def _get_next_serial_no(self):
        """Get the next message serial number"""
        self.msg_serial_no = (self.msg_serial_no + 1) % 0xFFFF
        return self.msg_serial_no
        
    def send_message(self, message):
        """
        Send a message to the server
        
        Args:
            message: Message object to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.connected:
            self.logger.error("Not connected to server")
            return False
            
        try:
            encoded_msg = message.encode()
            self.socket.sendall(encoded_msg)
            self.logger.debug(f"Sent message: {message.msg_id:04X}, length: {len(encoded_msg)} bytes")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message: {e}")
            return False
            
    def _receive_thread(self):
        """Thread to receive and process messages from the server"""
        buffer = bytearray()
        
        while self.connected:
            try:
                data = self.socket.recv(1024)
                if not data:
                    self.logger.error("Connection closed by server")
                    self.connected = False
                    break
                    
                buffer.extend(data)
                
                # Process complete messages in the buffer
                while len(buffer) > 2:
                    # Find start and end markers
                    start_idx = buffer.find(b'\x7e')
                    if start_idx == -1:
                        buffer.clear()
                        break
                        
                    # Remove any data before the start marker
                    if start_idx > 0:
                        buffer = buffer[start_idx:]
                        
                    # Find the end marker
                    end_idx = buffer.find(b'\x7e', 1)
                    if end_idx == -1:
                        # No complete message yet
                        break
                        
                    # Extract the complete message
                    message_data = buffer[:end_idx+1]
                    buffer = buffer[end_idx+1:]
                    
                    try:
                        # Decode the message
                        message = Message.decode(message_data)
                        self.logger.debug(f"Received message: {message.msg_id:04X}, length: {len(message_data)} bytes")
                        
                        # Handle special messages
                        if message.msg_id == MessageID.PLATFORM_GENERAL_RESPONSE:
                            self._handle_platform_response(message)
                        elif message.msg_id == MessageID.TERMINAL_REGISTRATION_RESPONSE:
                            self._handle_registration_response(message)
                        else:
                            # Put other messages in the queue for the application to handle
                            self.recv_queue.put(message)
                    except Exception as e:
                        self.logger.error(f"Failed to decode message: {e}")
            except Exception as e:
                if self.connected:
                    self.logger.error(f"Receive thread error: {e}")
                    
        self.logger.info("Receive thread terminated")
        
    def _handle_platform_response(self, message):
        """Handle platform general response message"""
        self.logger.debug(f"Platform response received: body_len={len(message.body)}, full_hex={message.body.hex() if message.body else 'empty'}")
        
        if len(message.body) < 5:
            self.logger.error(f"Invalid platform response message format: body length {len(message.body)}, expected at least 5 bytes")
            return
            
        try:
            # Only use the first 5 bytes for unpacking
            # The simulator may receive more than 5 bytes due to different protocol implementations
            response_data = message.body[:5]
            self.logger.debug(f"Using first 5 bytes for parsing: {response_data.hex()}")
            
            ack_serial_no, ack_id, result = struct.unpack('>HHB', response_data)
            
            self.logger.info(f"Platform response: serial={ack_serial_no}, msg_id={ack_id:04X}, result={result}")
            
            # Handle specific response types
            if ack_id == MessageID.TERMINAL_AUTH:
                if result == ResultCode.SUCCESS:
                    self.authenticated = True
                    self.logger.info("Authentication successful")
                else:
                    self.logger.error(f"Authentication failed with result code: {result}")
            
        except Exception as e:
            self.logger.error(f"Failed to parse platform response: {e}")
            # Try to partially parse what we can
            if len(message.body) >= 2:
                ack_serial_no = struct.unpack('>H', message.body[:2])[0]
                self.logger.debug(f"Partial parse - serial number: {ack_serial_no}")
                
                if len(message.body) >= 4:
                    ack_id = struct.unpack('>H', message.body[2:4])[0]
                    self.logger.debug(f"Partial parse - message ID: {ack_id:04X}")
                    
                    # For auth responses, set authenticated state
                    if ack_id == MessageID.TERMINAL_AUTH:
                        self.authenticated = True
                        self.logger.warning("Setting authenticated=True despite error parsing response")
            
    def _handle_registration_response(self, message):
        """Handle terminal registration response message"""
        # Add detailed logging
        self.logger.debug(f"Registration response received: body_len={len(message.body)}, full_hex={message.body.hex() if message.body else 'empty'}")
        
        if len(message.body) < 3:
            self.logger.error("Invalid registration response message format - body too short")
            return
            
        # Extract the serial number and result code
        ack_serial_no, result = struct.unpack('>HB', message.body[:3])
        self.logger.debug(f"Registration response: serial_no={ack_serial_no}, result={result}")
        
        if result == ResultCode.SUCCESS:
            if len(message.body) > 3:
                # Extract auth code
                auth_len = message.body[3]
                self.logger.debug(f"Auth code length byte: {auth_len}")
                
                if 4 + auth_len <= len(message.body):
                    auth_bytes = message.body[4:4+auth_len]
                    self.logger.debug(f"Auth code bytes: {auth_bytes.hex()}")
                    
                    try:
                        auth_code = auth_bytes.decode('utf-8')
                        self.auth_code = auth_code
                        self.logger.info(f"Registration successful, auth code: '{auth_code}'")
                        
                        # Automatically authenticate
                        self.authenticate(auth_code)
                    except Exception as e:
                        self.logger.error(f"Failed to decode auth code: {e}")
                        # Try with a default auth code
                        self.auth_code = "123456"
                        self.logger.warning(f"Using default auth code: {self.auth_code}")
                        self.authenticate(self.auth_code)
                else:
                    self.logger.error(f"Auth code length ({auth_len}) exceeds message boundary ({len(message.body) - 4})")
                    # Try with a default auth code
                    self.auth_code = "123456"
                    self.logger.warning(f"Using default auth code: {self.auth_code}")
                    self.authenticate(self.auth_code)
            else:
                self.logger.error("Registration response missing auth code field")
                # Try with a default auth code
                self.auth_code = "123456"
                self.logger.warning(f"Using default auth code: {self.auth_code}")
                self.authenticate(self.auth_code)
        else:
            self.logger.error(f"Registration failed, result: {result}")
            
    def register(self, province_id, city_id, manufacturer_id, terminal_model, terminal_id, 
               license_plate_color=0, license_plate=''):
        """
        Register the terminal with the platform
        
        Args:
            province_id: Province ID (2 bytes)
            city_id: City ID (2 bytes)
            manufacturer_id: Manufacturer ID (5 bytes string)
            terminal_model: Terminal model (20 bytes string)
            terminal_id: Terminal ID (7 bytes string)
            license_plate_color: License plate color (1 byte)
            license_plate: License plate number (string)
            
        Returns:
            True if the registration message was sent successfully, False otherwise
        """
        message = Message.create_registration(
            self.device_id, province_id, city_id, manufacturer_id, terminal_model, 
            terminal_id, license_plate_color, license_plate, self._get_next_serial_no()
        )
        
        return self.send_message(message)
        
    def authenticate(self, auth_code):
        """
        Authenticate the terminal with the platform
        
        Args:
            auth_code: Authentication code (string)
            
        Returns:
            True if the authentication message was sent successfully, False otherwise
        """
        message = Message.create_authentication(
            self.device_id, auth_code, self._get_next_serial_no()
        )
        
        return self.send_message(message)
        
    def send_heartbeat(self):
        """
        Send a heartbeat message to the platform
        
        Returns:
            True if the heartbeat message was sent successfully, False otherwise
        """
        message = Message.create_heartbeat(
            self.device_id, self._get_next_serial_no()
        )
        
        return self.send_message(message)
        
    def send_location(self, latitude, longitude, altitude=0, speed=0, direction=0, 
                    alarm_flag=0, status=0, additional_info=None):
        """
        Send a location report to the platform
        
        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees
            altitude: Altitude in meters
            speed: Speed in km/h
            direction: Direction in degrees (0-359)
            alarm_flag: Alarm flag (4 bytes)
            status: Status (4 bytes)
            additional_info: Dictionary of additional information items {id: value}
            
        Returns:
            True if the location report message was sent successfully, False otherwise
        """
        # Ensure parameters are of the correct type
        try:
            # Convert float coordinates to decimal degrees
            float_lat = float(latitude)
            float_lon = float(longitude)
            
            # Make sure numeric values are integers and within valid ranges
            int_altitude = int(altitude)
            # Ensure speed is within valid byte range (0-255)
            int_speed = min(255, max(0, int(speed)))
            # Ensure direction is within valid byte range (0-255)
            int_direction = min(255, max(0, int(direction % 256)))
            int_alarm_flag = int(alarm_flag)
            int_status = int(status)
            
            # Log the parameters for debugging
            self.logger.debug(f"Sending location: lat={float_lat}, lon={float_lon}, alt={int_altitude}, " +
                             f"speed={int_speed}, dir={int_direction}, alarm={int_alarm_flag}, status={int_status}")
            
            message = Message.create_location_report(
                self.device_id, int_alarm_flag, int_status, float_lat, float_lon, int_altitude, 
                int_speed, int_direction, None, additional_info, self._get_next_serial_no()
            )
        except Exception as e:
            self.logger.error(f"Error preparing location data: {e}")
            return False
        
        return self.send_message(message)
        
    def send_batch_location(self, locations, type_id=1):
        """
        Send a batch of location reports to the platform
        
        Args:
            locations: List of tuples (lat, lon, alt, speed, direction, alarm, status, additional_info)
            type_id: Data type (1: normal, 2: supplementary)
            
        Returns:
            True if the batch upload message was sent successfully, False otherwise
        """
        # Convert location tuples to location data bytes
        location_data_list = []
        
        for loc in locations:
            if len(loc) >= 7:
                lat, lon, alt, speed, direction, alarm, status = loc[:7]
                add_info = loc[7] if len(loc) > 7 else None
                
                # Create a location report message to format the data
                loc_msg = Message.create_location_report(
                    self.device_id, alarm, status, lat, lon, alt, 
                    speed, direction, None, add_info, self._get_next_serial_no()
                )
                
                location_data_list.append(loc_msg.body)
            
        # Create and send the batch upload message
        message = Message.create_batch_location_upload(
            self.device_id, location_data_list, type_id, self._get_next_serial_no()
        )
        
        return self.send_message(message)
        
    def logout(self):
        """
        Send a logout message to the platform
        
        Returns:
            True if the logout message was sent successfully, False otherwise
        """
        message = Message(
            MessageID.TERMINAL_LOGOUT, self.device_id, b'', self._get_next_serial_no()
        )
        
        return self.send_message(message)
        
    def receive_message(self, timeout=None):
        """
        Receive a message from the platform
        
        Args:
            timeout: Timeout in seconds, or None to block indefinitely
            
        Returns:
            Message object or None if timeout
        """
        try:
            return self.recv_queue.get(timeout=timeout)
        except queue.Empty:
            return None
