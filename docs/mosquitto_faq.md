# MQTT and Mosquitto FAQ

This FAQ covers common questions about using Mosquitto MQTT broker for the PetTracker system testing.

## General Questions

### What is MQTT?

MQTT (Message Queuing Telemetry Transport) is a lightweight publish/subscribe messaging protocol designed for IoT devices. It's ideal for remote locations where a small code footprint is required or network bandwidth is limited.

### What is Mosquitto?

Eclipse Mosquitto is an open-source message broker that implements the MQTT protocol versions 5.0, 3.1.1, and 3.1. It's lightweight and suitable for all devices from low-power single-board computers to full servers.

## Installation and Setup

### How do I install Mosquitto?

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
```

**macOS:**
```bash
brew install mosquitto
```

**Windows:**
Download the installer from [mosquitto.org](https://mosquitto.org/download/).

### How do I start Mosquitto manually?

```bash
# Start with a configuration file
mosquitto -c mosquitto.conf

# Start with verbose output for debugging
mosquitto -c mosquitto.conf -v
```

### What should my mosquitto.conf contain for PetTracker testing?

A basic configuration for testing should include:

```
# Basic MQTT protocol settings
listener 1883
allow_anonymous true
connection_messages true
log_type all

# Enable WebSockets for browser clients
listener 9001
protocol websockets
```

### How can I check if Mosquitto is running?

```bash
# Check process list
ps aux | grep mosquitto | grep -v grep

# Check if the port is open
netstat -tuln | grep 1883
```

## Troubleshooting

### Why can't I connect to the MQTT broker?

If you're having connection issues, check the following:

1. **Broker running:** Verify the Mosquitto broker is running with `ps aux | grep mosquitto`
2. **Port availability:** Make sure no other application is using port 1883 or 9001
3. **Firewall rules:** Ensure your firewall allows connections to these ports
4. **Connectivity:** From the client, try `telnet localhost 1883` to test basic connectivity
5. **Authentication:** Check if authentication is required (in our test setup, it should be anonymous)

### I'm not seeing any messages when subscribing. Why?

If you're subscribed but not seeing messages:

1. **Topic matching:** Ensure you're subscribed to the correct topic pattern (e.g., `pettracker/#`)
2. **Publisher status:** Verify the JT808 converter is running and properly configured
3. **Debug logs:** Check the converter logs for any errors in publishing messages
4. **Message format:** Ensure the converter is formatting messages correctly for MQTT

### How do I debug MQTT messages?

To see all messages passing through your broker:

```bash
# Subscribe to all topics
mosquitto_sub -h localhost -p 1883 -t "#" -v

# For a specific prefix with verbose output
mosquitto_sub -h localhost -p 1883 -t "pettracker/#" -v -d
```

## MQTT and the PetTracker System

### What MQTT topics does the PetTracker system use?

The PetTracker system uses the following topic structure:

- `pettracker/{device_id}/location` - Detailed location information
- `pettracker/{device_id}/heartbeat` - Device heartbeat messages
- `pettracker/{device_id}/status` - Device status updates
- `pettracker/tracking` - Combined real-time tracking information for all devices

### How does the JT808 converter interact with MQTT?

The converter:
1. Listens for JT/T 808-2013 protocol messages from GPS devices (or our simulator)
2. Converts the binary protocol data to JSON format
3. Publishes the JSON data to appropriate MQTT topics
4. Maintains device connections and acknowledges messages as needed

### What format are the MQTT messages in?

All messages are in JSON format. Here's an example location message:

```json
{
  "device_id": "123456789012",
  "timestamp": "2025-04-14T13:40:21Z",
  "event": "location",
  "location": {
    "latitude": 15.504273908,
    "longitude": -88.024932806,
    "altitude": 100,
    "speed": 5.0,
    "direction": 37
  },
  "status": {
    "acc_on": true,
    "location_fixed": true
  },
  "alarm": {
    "emergency": false
  },
  "additional": {}
}
```

## Using MQTT with Web Applications

### How can web applications connect to MQTT?

Web applications can connect to MQTT using:

1. **MQTT over WebSockets**: Most modern MQTT brokers (including Mosquitto) support WebSockets
2. **Client libraries**: Such as [MQTT.js](https://github.com/mqttjs/MQTT.js) for JavaScript applications

### Do I need a special configuration for web clients?

Yes, for web clients you need to:

1. Enable the WebSockets protocol in your Mosquitto configuration
2. Expose a WebSockets port (typically 9001)
3. Use the WebSockets URL format: `ws://hostname:9001`

### How can I test MQTT messages in a browser?

You can use the PetTracker's MQTT test page:

1. Navigate to http://localhost:5000/mqtt-test
2. Configure the connection settings (hostname, port, topic)
3. Click "Connect" to start receiving messages

Alternatively, you can use online tools like:
- [MQTT Explorer](http://mqtt-explorer.com/)
- [MQTT.fx](https://mqttfx.jensd.de/)
- [HiveMQ MQTT Client](http://www.hivemq.com/demos/websocket-client/)

## Advanced Usage

### How would I secure my MQTT broker for production?

For production environments, you should:

1. **Enable TLS/SSL**: Configure Mosquitto to use encrypted connections
2. **Set up authentication**: Use username/password or certificate-based authentication
3. **Restrict topics**: Use ACLs to restrict topic access based on client identity
4. **Configure secure ports**: Use standard secure ports (8883 for MQTT, 8884 for MQTT over WebSockets)

### How does the system transition from Mosquitto to AWS IoT?

To transition from local Mosquitto testing to AWS IoT:

1. Provision resources in AWS IoT Core
2. Generate and install the required certificates in the `certs/` directory
3. Update environment variables in the `.env` file to use the AWS configuration
4. Restart the converter to connect to AWS IoT instead of local Mosquitto
5. Frontend applications will need to be updated to connect to the AWS IoT endpoint

No protocol-level changes are needed as both support standard MQTT, but authentication and connection parameters will change.