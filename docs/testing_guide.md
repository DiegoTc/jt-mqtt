# PetTracker MQTT Pipeline Testing Guide

This guide provides detailed instructions for testing the JT/T 808-2013 to MQTT integration for the PetTracker system. It covers testing the local MQTT broker, the data converter, and the end-to-end pipeline.

## 1. Verifying the Mosquitto MQTT Broker

### Installing Mosquitto (if not already installed)

```bash
# System package installation
sudo apt install -y mosquitto mosquitto-clients   # Ubuntu/Debian
# or
brew install mosquitto                           # macOS with Homebrew
# or in our development environment
packager_tool install system mosquitto
```

### Configuring Mosquitto

The Mosquitto configuration file (`mosquitto.conf`) should be set up with the following settings:

```
# Default Mosquitto configuration for PetTracker testing
listener 1883
allow_anonymous true
connection_messages true
log_type all

# Persistence settings
persistence true
persistence_location /tmp/mosquitto/
persistence_file mosquitto.db

# Enable WebSockets support (for browser clients)
listener 9001
protocol websockets
```

### Starting the Mosquitto Broker

```bash
# Create the persistence directory
mkdir -p /tmp/mosquitto/

# Start Mosquitto in the background
nohup mosquitto -c mosquitto.conf > mosquitto.log 2>&1 &
```

### Verifying Mosquitto is Running

```bash
# Check if the Mosquitto process is running
ps aux | grep mosquitto | grep -v grep

# Check the Mosquitto log for successful startup
cat mosquitto.log

# Expected output should include lines like:
# mosquitto version 2.0.x starting
# Opening ipv4 listen socket on port 1883.
# Opening websockets listen socket on port 9001.
```

## 2. MQTT Message Testing with Subscription Client

### Basic Subscription

```bash
# Subscribe to all PetTracker topics
mosquitto_sub -h localhost -p 1883 -t "pettracker/#" -v

# Subscribe to specific topic types
mosquitto_sub -h localhost -p 1883 -t "pettracker/+/location" -v   # Only location updates
mosquitto_sub -h localhost -p 1883 -t "pettracker/+/heartbeat" -v  # Only heartbeats
mosquitto_sub -h localhost -p 1883 -t "pettracker/tracking" -v     # Real-time tracking topic
```

### Expected Output

When the converter is working correctly, you should see JSON messages like:

For the location topic:
```json
pettracker/123456789012/location {"device_id":"123456789012","timestamp":"2025-04-14T13:40:21Z","event":"location","location":{"latitude":15.504273908,"longitude":-88.024932806,"altitude":100,"speed":5.0,"direction":37},"status":{"acc_on":true,"location_fixed":true},"alarm":{"emergency":false},"additional":{}}
```

For the heartbeat topic:
```json
pettracker/123456789012/heartbeat {"device_id":"123456789012","timestamp":"2025-04-14T13:40:19Z","event":"heartbeat"}
```

For the tracking topic:
```json
pettracker/tracking {"device_id":"123456789012","timestamp":"2025-04-14T13:40:21Z","latitude":15.504273908,"longitude":-88.024932806,"speed":5.0,"direction":37}
```

## 3. End-to-End Data Pipeline Testing

### Step 1: Start the Mosquitto MQTT Broker

```bash
# Ensure Mosquitto is running
ps aux | grep mosquitto | grep -v grep

# If not running, start it
mkdir -p /tmp/mosquitto/
nohup mosquitto -c mosquitto.conf > mosquitto.log 2>&1 &
```

### Step 2: Start the JT808 to MQTT Converter

```bash
# Start the converter service
# If using the web interface
# Navigate to http://localhost:5000 and use the Start Converter button

# If starting from command line
python converter.py -v
```

Verify in the logs that:
- The converter successfully starts
- It connects to the MQTT broker (look for "Connected to MQTT broker at localhost:1883")
- It's listening for JT808 connections (look for "JT808 Server listening on 0.0.0.0:8008")

### Step 3: Start the JT808 Simulator

```bash
# Start the simulator
python simulator.py -v
```

Verify in the logs that:
- The simulator connects to the converter (look for "Connected to 127.0.0.1:8008")
- It successfully registers (look for "Registration successful")
- It authenticates (look for "Authentication successful")
- It's sending location data (look for "Sending location: lat=XX.XX, lon=YY.YY")

### Step 4: Verify MQTT Messages

In a separate terminal, run the MQTT subscription tool:

```bash
mosquitto_sub -h localhost -p 1883 -t "pettracker/#" -v
```

Verify that:
- You see JSON-formatted messages for each location update from the simulator
- The messages contain the correct location coordinates, matching what the simulator is sending
- The format follows the expected schema with device_id, timestamp, latitude, longitude, etc.
- Messages are coming through in real-time as the simulator updates

## 4. Debugging Common Issues

### MQTT Broker Issues

If the broker doesn't start:
```bash
# Check for port conflicts
netstat -tuln | grep 1883

# Try starting with verbose output
mosquitto -c mosquitto.conf -v
```

### Converter Issues

If the converter fails to connect to MQTT:
```bash
# Check .env file for correct MQTT settings
cat .env

# Make sure the broker is running
ps aux | grep mosquitto

# Check converter logs for connection errors
```

### Simulator Issues

If the simulator cannot connect to the converter:
```bash
# Verify the converter is running and listening on port 8008
netstat -tuln | grep 8008

# Check config.json for correct connection settings
cat config.json

# Check simulator logs for connection errors
```

## 5. Testing Frontend Integration

### Option 1: Using a Web Client to Subscribe to MQTT

You can use the [MQTT Explorer](http://mqtt-explorer.com/) or [MQTT.fx](https://mqttfx.jensd.de/) desktop applications to:
- Connect to your local MQTT broker
- Subscribe to the `pettracker/#` topics
- Visualize the data coming in

### Option 2: Simple Web Page for Testing

Create a simple HTML page with Mapbox and MQTT.js to test frontend integration:

```html
<!DOCTYPE html>
<html>
<head>
    <title>PetTracker Test</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://unpkg.com/mqtt/dist/mqtt.min.js"></script>
    <script src='https://api.mapbox.com/mapbox-gl-js/v2.8.1/mapbox-gl.js'></script>
    <link href='https://api.mapbox.com/mapbox-gl-js/v2.8.1/mapbox-gl.css' rel='stylesheet' />
    <style>
        body { margin: 0; padding: 0; }
        #map { position: absolute; top: 0; bottom: 0; width: 100%; }
        #info { position: absolute; top: 10px; right: 10px; z-index: 1; background: white; padding: 10px; border-radius: 4px; }
    </style>
</head>
<body>
    <div id="map"></div>
    <div id="info">Waiting for MQTT data...</div>

    <script>
        // Initialize map
        mapboxgl.accessToken = 'YOUR_MAPBOX_ACCESS_TOKEN';
        const map = new mapboxgl.Map({
            container: 'map',
            style: 'mapbox://styles/mapbox/streets-v11',
            center: [-88.02, 15.50], // Honduras coordinates
            zoom: 16
        });

        // Add marker for pet location
        const marker = new mapboxgl.Marker()
            .setLngLat([-88.02, 15.50])
            .addTo(map);

        // Connect to MQTT over WebSockets
        const client = mqtt.connect('ws://localhost:9001');

        client.on('connect', function() {
            console.log('Connected to MQTT broker');
            document.getElementById('info').innerText = 'Connected to MQTT broker';
            
            // Subscribe to the tracking topic
            client.subscribe('pettracker/tracking');
        });

        client.on('message', function(topic, message) {
            const data = JSON.parse(message.toString());
            console.log('Received update:', data);
            
            // Update info display
            document.getElementById('info').innerText = 
                `Pet: ${data.device_id}\nLat: ${data.latitude.toFixed(6)}\nLng: ${data.longitude.toFixed(6)}\nSpeed: ${data.speed} km/h\nTime: ${data.timestamp}`;
            
            // Update marker position
            marker.setLngLat([data.longitude, data.latitude]);
            
            // Center map on new position
            map.setCenter([data.longitude, data.latitude]);
        });

        client.on('error', function(error) {
            console.error('MQTT error:', error);
            document.getElementById('info').innerText = 'MQTT Error: ' + error.message;
        });
    </script>
</body>
</html>
```

Save this as `test_map.html` and open it in a browser to test the full integration.

## 6. Testing AWS IoT Integration (Future Production Setup)

For testing the AWS IoT integration when ready:

1. Place AWS IoT certificates in the `certs/` directory:
   - `AmazonRootCA1.pem`
   - `certificate.pem.crt`
   - `private.pem.key`

2. Update `.env` file to use AWS IoT:
   ```
   MQTT_BROKER_TYPE=aws
   AWS_MQTT_ENDPOINT=your-iot-endpoint.iot.region.amazonaws.com
   AWS_MQTT_PORT=8883
   AWS_MQTT_CLIENT_ID=pettracker-converter
   AWS_MQTT_TOPIC_PREFIX=pettracker
   ```

3. Run the converter as normal and verify connections to AWS IoT in the logs.

## Conclusion

The testing process should verify:

1. The Mosquitto MQTT broker is running correctly
2. The JT808 to MQTT converter is successfully receiving JT808 protocol data and converting it
3. The converter is publishing properly formatted JSON to the MQTT broker
4. The complete data pipeline functions end-to-end
5. (Optional) The data can be consumed by frontend applications

When all of these steps are working, you can be confident that the local MQTT testing environment is functioning correctly before moving to AWS IoT in production.