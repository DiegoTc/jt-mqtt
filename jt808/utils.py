"""
Utility functions for JT/T 808-2013 protocol
"""
import struct
import time
import logging
import datetime

def reverse_hex(hex_str):
    """Reverses byte order in hex string for display"""
    if len(hex_str) % 2 != 0:
        raise ValueError("Hex string length must be even")
    return ''.join(reversed([hex_str[i:i+2] for i in range(0, len(hex_str), 2)]))

def bytes_to_bcd(data):
    """Convert a bytes object to BCD representation"""
    return ''.join([f'{b:02x}' for b in data])

def bcd_to_bytes(bcd_str):
    """Convert a BCD string to bytes"""
    if len(bcd_str) % 2 != 0:
        bcd_str = '0' + bcd_str
    return bytes.fromhex(bcd_str)

def calculate_checksum(data):
    """
    Calculate checksum using XOR operation on each byte
    
    Args:
        data: bytes to calculate checksum for
        
    Returns:
        Single byte checksum
    """
    checksum = 0
    for b in data:
        checksum ^= b
    return checksum

def apply_escape_rules(data):
    """
    Apply the escape rules to the data:
    - 0x7e is replaced with 0x7d followed by 0x02
    - 0x7d is replaced with 0x7d followed by 0x01
    
    Args:
        data: bytes to apply escape rules to
        
    Returns:
        Escaped bytes
    """
    escaped = bytearray()
    for b in data:
        if b == 0x7e:
            escaped.extend(b'\x7d\x02')
        elif b == 0x7d:
            escaped.extend(b'\x7d\x01')
        else:
            escaped.append(b)
    return bytes(escaped)

def remove_escape_rules(data):
    """
    Remove the escape rules from the data:
    - 0x7d followed by 0x02 is replaced with 0x7e
    - 0x7d followed by 0x01 is replaced with 0x7d
    
    Args:
        data: escaped bytes
        
    Returns:
        Original bytes
    """
    unescaped = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0x7d and i + 1 < len(data):
            if data[i + 1] == 0x02:
                unescaped.append(0x7e)
                i += 2
            elif data[i + 1] == 0x01:
                unescaped.append(0x7d)
                i += 2
            else:
                unescaped.append(data[i])
                i += 1
        else:
            unescaped.append(data[i])
            i += 1
    return bytes(unescaped)

def get_current_timestamp():
    """Get current timestamp in the format required by the protocol (BCD)"""
    now = datetime.datetime.now()
    # Format: YYMMDDhhmmss
    return f'{now.year % 100:02d}{now.month:02d}{now.day:02d}{now.hour:02d}{now.minute:02d}{now.second:02d}'

def parse_bcd_timestamp(bcd_timestamp):
    """Parse BCD timestamp into a datetime object"""
    timestamp_str = bytes_to_bcd(bcd_timestamp)
    year = 2000 + int(timestamp_str[0:2])
    month = int(timestamp_str[2:4])
    day = int(timestamp_str[4:6])
    hour = int(timestamp_str[6:8])
    minute = int(timestamp_str[8:10])
    second = int(timestamp_str[10:12])
    return datetime.datetime(year, month, day, hour, minute, second)

def decimal_to_dms(decimal_degrees):
    """
    Convert decimal degrees to degrees-minutes-seconds format used in the protocol
    The protocol stores coordinates as: degrees*10^6 + minutes*10^4 + seconds*10^2
    """
    degrees = int(decimal_degrees)
    minutes_float = (decimal_degrees - degrees) * 60
    minutes = int(minutes_float)
    seconds = int((minutes_float - minutes) * 60)
    
    # Return in the format required by the protocol (degrees*10^6 + minutes*10^4 + seconds*10^2)
    return (degrees * 1000000) + (minutes * 10000) + (seconds * 100)

def dms_to_decimal(dms_value):
    """
    Convert degrees-minutes-seconds format to decimal degrees
    """
    degrees = dms_value // 1000000
    minutes = (dms_value % 1000000) // 10000
    seconds = (dms_value % 10000) // 100
    
    return degrees + (minutes / 60) + (seconds / 3600)
