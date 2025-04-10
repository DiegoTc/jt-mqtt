"""
Constants for JT/T 808-2013 protocol
"""

class MessageID:
    """Message IDs as defined in the JT/T 808-2013 protocol"""
    # Terminal -> Platform
    TERMINAL_GENERAL_RESPONSE = 0x0001
    TERMINAL_HEARTBEAT = 0x0002
    TERMINAL_LOGOUT = 0x0003
    TERMINAL_REGISTRATION = 0x0100
    TERMINAL_AUTH = 0x0102
    TERMINAL_ATTRIBUTE_REPORT = 0x0107
    LOCATION_REPORT = 0x0200
    LOCATION_INFO_QUERY_RESPONSE = 0x0201
    BATCH_LOCATION_UPLOAD = 0x0704
    
    # Platform -> Terminal
    PLATFORM_GENERAL_RESPONSE = 0x8001
    TERMINAL_REGISTRATION_RESPONSE = 0x8100
    SET_TERMINAL_PARAMETERS = 0x8103
    TERMINAL_CONTROL = 0x8105
    LOCATION_INFO_QUERY = 0x8201
    TEMP_POSITION_TRACKING = 0x8202
    
    # Custom protocols
    REQUEST_SYNC_TIME = 0x0109
    SYNC_TIME_RESPONSE = 0x8109
    SMS_CENTER_NUMBER = 0x0818

# Status bit definitions
class StatusBit:
    """Status bit definitions for location information"""
    ACC_ON = 0x1  # Bit 0
    LOCATION_FIXED = 0x2  # Bit 1
    LAT_SOUTH = 0x4  # Bit 2, otherwise North
    LON_WEST = 0x8  # Bit 3, otherwise East
    IN_OPERATION = 0x10  # Bit 4
    ENCRYPTED = 0x20  # Bit 5
    # ... other status bits as needed

# Alarm flag definitions
class AlarmFlag:
    """Alarm flag definitions for location information"""
    EMERGENCY = 0x1  # Bit 0
    OVERSPEED = 0x2  # Bit 1
    FATIGUE_DRIVING = 0x4  # Bit 2
    DANGER_WARNING = 0x8  # Bit 3
    GNSS_MODULE_FAULT = 0x10  # Bit 4
    GNSS_ANTENNA_DISCONNECTED = 0x20  # Bit 5
    GNSS_ANTENNA_SHORT_CIRCUIT = 0x40  # Bit 6
    TERMINAL_MAIN_POWER_UNDERVOLTAGE = 0x80  # Bit 7
    # ... other alarm flags as needed

# Result codes for responses
class ResultCode:
    """Result codes for general responses"""
    SUCCESS = 0
    FAILURE = 1
    MESSAGE_ERROR = 2
    UNSUPPORTED = 3
    ALARM_PROCESSING_CONFIRMATION = 4

# Additional information IDs for location reports
class AdditionalInfoID:
    """Additional information IDs for location reports"""
    MILEAGE = 0x01
    OIL = 0x02
    SPEED = 0x03
    ALTITUDE = 0x04
