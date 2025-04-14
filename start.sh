#!/bin/bash

# Load environment variables from .env file if it exists
if [ -f .env ]; then
  export $(cat .env | grep -v '#' | awk '/=/ {print $1}')
fi

# Use PORT from environment or default to 8080
PORT=${PORT:-8080}

# Start gunicorn with the specified port
exec gunicorn --bind 0.0.0.0:$PORT --reuse-port --reload main:app