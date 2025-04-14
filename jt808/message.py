"""
Message class for JT/T 808-2013 protocol
"""
import struct
import time
import logging
from jt808.utils import calculate_checksum, apply_escape_rules, remove_escape_rules, get_current_timestamp
from jt808.constants import MessageID

class Message:
    """
    Represents a JT/T 808-2013 protocol message
    """
    def __init__(self, msg_id, phone_no, body=None, msg_serial_no=0, is_subpackage=False, 
                 encrypted=False, subpackage_info=None):
        """
        Initialize a new message
        
        Args:
            msg_id: Message ID (2 bytes)
            phone_no: Phone number (device ID, max 6 bytes)
            body: Message body (bytes or None)
            msg_serial_no: Message serial number (2 bytes)
            is_subpackage: Whether the message is a subpackage
            encrypted: Whether the message body is encrypted
            subpackage_info: Subpackage information (tuple of total, seq)
        """
        self.msg_id = msg_id
        self.phone_no = phone_no
        self.body = body if body is not None else b''
        self.msg_serial_no = msg_serial_no
        self.is_subpackage = is_subpackage
        self.encrypted = encrypted
        self.subpackage_info = subpackage_info
        
    def get_body_attr(self):
        """Calculate message body attributes field"""
        attr = len(self.body)  # Bits 0-9: Message body length
        
        if self.encrypted:
            attr |= 0x400  # Bit 10: RSA encryption flag
            
        if self.is_subpackage:
            attr |= 0x2000  # Bit 13: Subpackage flag
            
        return attr
    
    def encode(self):
        """
        Encode the message according to the protocol
        
        Returns:
            The encoded message as bytes
        """
        # Prepare the phone number (device ID)
        # Ensure we only use the last 12 digits (6 bytes) if phone_no is longer
        try:
            # Make sure phone_no is a string first
            phone_str = str(self.phone_no)
            # Try to clean it up in case it's not a pure numeric string
            if not phone_str.isdigit():
                # If it contains non-digit chars, try to extract digits only
                import re
                digits_only = re.sub(r'\D', '', phone_str)
                if digits_only:
                    phone_str = digits_only
                else:
                    # If we can't get digits, generate a fallback ID
                    import random
                    phone_str = f"{random.randint(100000000000, 999999999999)}"
                    
            if len(phone_str) > 12:
                phone_str = phone_str[-12:]  # Take the last 12 digits
            elif len(phone_str) < 12:
                # Pad with zeros if necessary
                phone_str = phone_str.zfill(12)
                
            phone_bytes = bytes(f'{phone_str}', 'ascii')
        except Exception as e:
            import logging
            logging.error(f"Error preparing phone number: {e}, phone_no={self.phone_no}, type={type(self.phone_no)}")
            # Fallback to a default phone number
            phone_bytes = b'000000000000'
        
        # Prepare message header
        msg_header = struct.pack('>HH6sHH',
                                self.msg_id,
                                self.get_body_attr(),
                                phone_bytes,
                                self.msg_serial_no,
                                0x00)  # Default packet count and packet number
        
        # Add subpackage info if required
        if self.is_subpackage and self.subpackage_info:
            total_pkg, pkg_seq = self.subpackage_info
            subpackage_data = struct.pack('>HH', total_pkg, pkg_seq)
            msg_header += subpackage_data
            
        # Combine header and body
        msg_data = msg_header + self.body
        
        # Calculate checksum
        checksum = calculate_checksum(msg_data)
        
        # Apply escape rules
        escaped_data = apply_escape_rules(msg_data + bytes([checksum]))
        
        # Frame with 0x7e
        return b'\x7e' + escaped_data + b'\x7e'
    
    @classmethod
    def decode(cls, data):
        """
        Decode a message according to the protocol
        
        Args:
            data: The raw message data as bytes
            
        Returns:
            A Message object
        """
        # Verify frame start and end
        if not (data.startswith(b'\x7e') and data.endswith(b'\x7e')):
            raise ValueError("Invalid message framing: must start and end with 0x7e")
            
        # Remove framing
        data = data[1:-1]
        
        # Remove escape rules
        unescaped_data = remove_escape_rules(data)
        
        # Verify checksum
        msg_data = unescaped_data[:-1]
        received_checksum = unescaped_data[-1]
        calculated_checksum = calculate_checksum(msg_data)
        
        if received_checksum != calculated_checksum:
            raise ValueError(f"Checksum verification failed: received {received_checksum}, calculated {calculated_checksum}")
            
        # Parse header
        # Basic header fields (without subpackage)
        min_header_len = 12
        if len(msg_data) < min_header_len:
            raise ValueError(f"Message data too short: {len(msg_data)} bytes, minimum {min_header_len}")
            
        msg_id, body_attr, phone_bcd, msg_serial_no, pkg_info = struct.unpack('>HH6sHH', msg_data[:min_header_len])
        # Make sure we're handling the phone number correctly (it's already in bytes format)
        try:
            # If it's in BCD format
            phone_no = phone_bcd.decode('ascii')
        except Exception as e:
            # As a fallback, try to represent the bytes directly
            phone_no = ''.join([f'{b:02x}' for b in phone_bcd]).upper()
        
        # Check if subpackage
        is_subpackage = bool(body_attr & 0x2000)
        encrypted = bool(body_attr & 0x400)
        
        # If subpackage, parse subpackage info
        header_len = min_header_len
        subpackage_info = None
        
        if is_subpackage:
            if len(msg_data) < min_header_len + 4:
                raise ValueError("Message data too short for subpackage info")
                
            total_pkg, pkg_seq = struct.unpack('>HH', msg_data[min_header_len:min_header_len+4])
            subpackage_info = (total_pkg, pkg_seq)
            header_len += 4
            
        # Extract body
        body = msg_data[header_len:]
        
        return cls(msg_id, phone_no, body, msg_serial_no, is_subpackage, encrypted, subpackage_info)

    # Helper methods for common messages
    @classmethod
    def create_heartbeat(cls, phone_no, msg_serial_no=None):
        """Create a terminal heartbeat message"""
        if msg_serial_no is None:
            msg_serial_no = int(time.time()) % 0xFFFF
        return cls(MessageID.TERMINAL_HEARTBEAT, phone_no, b'', msg_serial_no)
    
    @classmethod
    def create_registration(cls, phone_no, province_id, city_id, manufacturer_id, 
                          terminal_model, terminal_id, license_plate_color, license_plate,
                          msg_serial_no=None):
        """Create a terminal registration message"""
        if msg_serial_no is None:
            msg_serial_no = int(time.time()) % 0xFFFF
            
        # Format body according to Table 6
        body = struct.pack('>HH5s20s7sB',
                         province_id,
                         city_id,
                         manufacturer_id.encode('ascii'),
                         terminal_model.encode('ascii'),
                         terminal_id.encode('ascii'),
                         license_plate_color)
        
        # Add license plate as string with length byte
        license_bytes = license_plate.encode('utf-8')
        body += bytes([len(license_bytes)]) + license_bytes
        
        return cls(MessageID.TERMINAL_REGISTRATION, phone_no, body, msg_serial_no)
    
    @classmethod
    def create_authentication(cls, phone_no, auth_code, msg_serial_no=None):
        """Create a terminal authentication message"""
        if msg_serial_no is None:
            msg_serial_no = int(time.time()) % 0xFFFF
            
        # Format body according to Table 8
        auth_bytes = auth_code.encode('utf-8')
        body = bytes([len(auth_bytes)]) + auth_bytes
        
        return cls(MessageID.TERMINAL_AUTH, phone_no, body, msg_serial_no)
    
    @classmethod
    def create_location_report(cls, phone_no, alarm_flag, status, latitude, longitude,
                             altitude=0, speed=0, direction=0, timestamp=None, 
                             additional_info=None, msg_serial_no=None):
        """
        Create a location information report message
        
        Args:
            phone_no: Phone number (device ID)
            alarm_flag: Alarm flag (4 bytes)
            status: Status (4 bytes)
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees
            altitude: Altitude in meters
            speed: Speed in km/h
            direction: Direction in degrees (0-359)
            timestamp: BCD timestamp (YYMMDDhhmmss)
            additional_info: Dictionary of additional information items {id: value}
            msg_serial_no: Message serial number
        """
        from jt808.utils import decimal_to_dms
        
        if msg_serial_no is None:
            msg_serial_no = int(time.time()) % 0xFFFF
            
        if timestamp is None:
            timestamp = get_current_timestamp()
            
        # Convert latitude and longitude to protocol format (degrees*10^6 + minutes*10^4 + seconds*10^2)
        lat_value = decimal_to_dms(abs(latitude))
        lon_value = decimal_to_dms(abs(longitude))
        
        # Set direction flags based on latitude and longitude signs
        if latitude < 0:  # South
            status |= 0x4
        if longitude < 0:  # West
            status |= 0x8
            
        # Format basic location information according to Table 16
        body = struct.pack('>IIIIHHBBBBB',
                         alarm_flag,
                         status,
                         lat_value,
                         lon_value,
                         altitude,
                         speed,
                         direction,
                         int(timestamp[0:2], 16),  # Year
                         int(timestamp[2:4], 16),  # Month
                         int(timestamp[4:6], 16),  # Day
                         int(timestamp[6:8], 16))  # Hour
                         
        # Add minutes and seconds
        body += bytes([int(timestamp[8:10], 16), int(timestamp[10:12], 16)])
        
        # Add additional information items if provided
        if additional_info:
            for info_id, info_value in additional_info.items():
                # Format: ID (1 byte) + Length (1 byte) + Value (n bytes)
                if isinstance(info_value, int):
                    if info_id == 0x01:  # Mileage (4 bytes)
                        body += struct.pack('>BBI', info_id, 4, info_value)
                    elif info_id == 0x02:  # Oil (2 bytes)
                        body += struct.pack('>BBH', info_id, 2, info_value)
                    elif info_id == 0x03 or info_id == 0x04:  # Speed or Altitude (2 bytes)
                        body += struct.pack('>BBH', info_id, 2, info_value)
                    else:
                        # Default to 4 bytes for other integer values
                        body += struct.pack('>BBI', info_id, 4, info_value)
                else:
                    # If not an integer, treat as bytes
                    value_bytes = info_value if isinstance(info_value, bytes) else str(info_value).encode('utf-8')
                    body += bytes([info_id, len(value_bytes)]) + value_bytes
        
        return cls(MessageID.LOCATION_REPORT, phone_no, body, msg_serial_no)
    
    @classmethod
    def create_batch_location_upload(cls, phone_no, locations, type_id=1, msg_serial_no=None):
        """
        Create a batch upload of positioning data message
        
        Args:
            phone_no: Phone number (device ID)
            locations: List of location data items (each a tuple of location data)
            type_id: Data type (1: normal, 2: supplementary)
            msg_serial_no: Message serial number
        """
        if msg_serial_no is None:
            msg_serial_no = int(time.time()) % 0xFFFF
            
        # Format according to Table 76
        body = struct.pack('>BH', type_id, len(locations))
        
        for location_data in locations:
            # Process location data according to create_location_report format
            # This should be extracted from a LocationReport message or formatted the same way
            body += location_data
            
        return cls(MessageID.BATCH_LOCATION_UPLOAD, phone_no, body, msg_serial_no)
    
    @classmethod
    def create_platform_general_response(cls, phone_no, ack_serial_no, ack_id, result, msg_serial_no=None):
        """Create a platform general response message"""
        if msg_serial_no is None:
            msg_serial_no = int(time.time()) % 0xFFFF
            
        # Format body according to Table 5
        body = struct.pack('>HHB', ack_serial_no, ack_id, result)
        
        return cls(MessageID.PLATFORM_GENERAL_RESPONSE, phone_no, body, msg_serial_no)
