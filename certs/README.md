# AWS IoT Certificates Directory

This directory stores the certificates required for secure connection to AWS IoT Core. When transitioning from local testing to AWS production, place the following files here:

- `AmazonRootCA1.pem`: The Amazon root CA certificate
- `certificate.pem.crt`: Your device certificate from AWS IoT
- `private.pem.key`: Your private key from AWS IoT

## How to Obtain AWS IoT Credentials

1. Log in to the AWS Management Console and navigate to the AWS IoT Core service
2. Create a new thing or use an existing one
3. Register a CA certificate and create a client certificate
4. Download the certificates and keys
5. Place them in this directory with the names specified above

## Local Testing

For local development and testing, the system will use Mosquitto MQTT broker, and these certificates aren't required. Set `MQTT_BROKER_TYPE=local` in your `.env` file for local development.

## Security Notice

Never commit actual certificates to version control. This directory is included in `.gitignore` to prevent accidental exposure of credentials.