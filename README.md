# JT/T 808-2013 GPS Tracker Simulator with MQTT Converter

This project provides a complete implementation of a JT/T 808-2013 GPS tracking simulator and a converter that translates the protocol messages to MQTT format. It includes a web interface for easy configuration and monitoring.

## Features

### GPS Tracking Simulator
- Implementation of JT/T 808-2013 protocol
- Simulates GPS device movement
- Supports terminal registration, authentication, heartbeat, and location reporting
- Configurable parameters (device ID, coordinates, movement, etc.)
- Support for batch location reports

### MQTT Converter
- Listens for JT/T 808 messages on a TCP socket
- Decodes and parses the protocol messages
- Converts messages to JSON format
- Publishes to appropriate MQTT topics
- Handles multiple client connections

### Web Interface
- Configure both simulator and converter
- Monitor logs in real-time
- Visualize GPS tracking on a map
- Control simulator and converter operations

## Installation

### Prerequisites
- Python 3.6 or higher
- Required packages: flask, paho-mqtt

```bash
pip install flask paho-mqtt
```

## Running Locally

### 1. Clone the Repository

```bash
git clone https://github.com/DiegoTc/jt-mqtt.git
cd jt-mqtt
```

### 2. Configuration

The default configuration is stored in `config.json`. You can modify this file directly or use the web interface to update settings.

Key configuration options:
- `server_ip` and `server_port`: The IP and port the simulator will connect to
- `jt808_host` and `jt808_port`: The host and port the converter will listen on
- `mqtt_host` and `mqtt_port`: MQTT broker settings

### 3. Start the Web Interface

You can start the web interface using one of the following methods:

```bash
# Method 1: Using Python directly (uses port 8080)
python main.py

# Method 2: Using the start script (uses port from .env file or defaults to 8080)
./start.sh
```

This will start a web server on port 8080. Open your browser and navigate to `http://localhost:8080`.

You can change the port by creating a `.env` file based on the provided `.env.example`:

```
# Create a .env file
cp .env.example .env
# Edit the PORT value in .env
PORT=8080  # Change to your preferred port
```

### 4. Using the Web Interface

1. **Configuration**
   - Configure simulator settings (device ID, location, intervals, etc.)
   - Configure converter settings (JT808 server, MQTT broker, etc.)
   - Save changes using the "Save Configuration" buttons

2. **Start the Converter**
   - Click the "Start" button in the MQTT Converter section
   - The converter will listen for JT808 messages on the configured port

3. **Start the Simulator**
   - Click the "Start" button in the Simulator section
   - The simulator will connect to the converter and start sending messages

4. **Monitor Activity**
   - View logs in real-time in the log sections
   - Track simulated movement on the map

### 5. Running Components Separately

You can also run the simulator or converter separately using:

```bash
# Run the simulator
python simulator.py -v

# Run the converter
python converter.py -v
```

Use the `-v` flag for verbose logging. Add `-h` to see all available options.

## Protocol Implementation

The implementation follows the JT/T 808-2013 protocol with support for the following message types:

### Terminal → Platform
- Terminal heartbeat (0x0002)
- Terminal registration (0x0100)
- Terminal authentication (0x0102)
- Location report (0x0200)
- Batch location upload (0x0704)
- Terminal logout (0x0003)

### Platform → Terminal
- Platform general response (0x8001)
- Terminal registration response (0x8100)
- Terminal control commands

## MQTT Topics

The converter publishes messages to the following MQTT topics:

- `{prefix}/{device_id}/heartbeat` - Heartbeat events
- `{prefix}/{device_id}/registration` - Registration information
- `{prefix}/{device_id}/authentication` - Authentication events
- `{prefix}/{device_id}/location` - Location reports
- `{prefix}/{device_id}/batch_location` - Batch location uploads
- `{prefix}/{device_id}/status` - Device status (online/offline)

Where `{prefix}` is the configured MQTT topic prefix (default: `jt808`) and `{device_id}` is the device identifier.

## Testing

Comprehensive testing guides are available to help you verify and troubleshoot your setup:

- **Testing Guide**: Step-by-step instructions for testing the MQTT pipeline [docs/testing_guide.md](docs/testing_guide.md)
- **Mosquitto FAQ**: Common questions about using the MQTT broker [docs/mosquitto_faq.md](docs/mosquitto_faq.md)
- **Test MQTT Page**: A web interface for monitoring MQTT messages at [http://localhost:5000/mqtt-test](http://localhost:5000/mqtt-test)
- **Test Environment Script**: Automated setup of the testing environment using [start_test_environment.sh](start_test_environment.sh)

### Testing the MQTT Pipeline

To quickly test the entire pipeline:

1. **Start the MQTT broker**:
   ```bash
   mkdir -p /tmp/mosquitto/
   mosquitto -c mosquitto.conf > mosquitto.log 2>&1 &
   ```

2. **Start the converter and simulator** via web interface:
   - Navigate to [http://localhost:5000](http://localhost:5000)
   - Click "Start Converter" then "Start Simulator"
   
3. **Monitor MQTT messages**:
   ```bash
   mosquitto_sub -h localhost -p 1883 -t "pettracker/#" -v
   ```

See the comprehensive [testing guide](docs/testing_guide.md) for detailed steps and troubleshooting.

## Troubleshooting

1. **Connection Issues**
   - Ensure the converter is started before the simulator
   - Check that port settings in configuration match
   - Verify no other service is using the same ports

2. **MQTT Connection Problems**
   - Check MQTT broker connection settings
   - Verify the broker is running and accessible
   - Use `mosquitto_sub -t "#" -v` to monitor all MQTT traffic
   - Check broker logs with `cat mosquitto.log`

3. **Logging**
   - Enable verbose mode (-v) for detailed logs
   - Check the logs for specific error messages
   - View real-time logs in the web interface

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Based on the JT/T 808-2013 protocol specification
- Uses Leaflet for map visualization