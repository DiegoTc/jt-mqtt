#!/bin/bash

# PetTracker Test Environment Startup Script
# This script automates the startup of the PetTracker MQTT testing environment

# Set colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== PetTracker MQTT Testing Environment Startup ===${NC}"

# Step 1: Ensure directories exist
mkdir -p /tmp/mosquitto/
echo -e "${GREEN}✓ Created temporary directories${NC}"

# Step 2: Check if Mosquitto is already running
if pgrep mosquitto > /dev/null; then
    echo -e "${YELLOW}⚠ Mosquitto broker is already running${NC}"
    
    # Ask if we should kill and restart
    read -p "Do you want to kill the running instance and restart? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pkill mosquitto
        echo -e "${GREEN}✓ Stopped existing Mosquitto broker${NC}"
    else
        echo -e "${YELLOW}Continuing with existing Mosquitto broker...${NC}"
    fi
fi

# Step 3: Start Mosquitto broker
echo -e "${YELLOW}Starting Mosquitto MQTT broker...${NC}"
nohup mosquitto -c mosquitto.conf > mosquitto.log 2>&1 &
MOSQUITTO_PID=$!
sleep 2

# Check if Mosquitto started successfully
if pgrep -P $MOSQUITTO_PID > /dev/null || pgrep mosquitto > /dev/null; then
    echo -e "${GREEN}✓ Mosquitto broker started successfully${NC}"
else
    echo -e "${RED}✗ Failed to start Mosquitto broker. Check mosquitto.log for details.${NC}"
    exit 1
fi

# Step 4: Start the converter if requested
echo -e "${YELLOW}Do you want to start the JT808 to MQTT converter? (y/n)${NC}"
read -p "" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Starting JT808 to MQTT converter...${NC}"
    
    # Check if running through web interface or directly
    echo -e "${YELLOW}Start through: (1) Web interface or (2) Command line?${NC}"
    read -p "Enter 1 or 2: " start_method
    echo
    
    if [ "$start_method" -eq 1 ]; then
        echo -e "${GREEN}✓ Please navigate to http://localhost:5000 and click 'Start Converter'${NC}"
    else
        nohup python converter.py -v > converter.log 2>&1 &
        CONVERTER_PID=$!
        sleep 2
        
        # Check if converter started successfully
        if ps -p $CONVERTER_PID > /dev/null; then
            echo -e "${GREEN}✓ JT808 to MQTT converter started successfully (PID: $CONVERTER_PID)${NC}"
            echo -e "${YELLOW}Converter logs are being written to converter.log${NC}"
        else
            echo -e "${RED}✗ Failed to start converter. Check converter.log for details.${NC}"
        fi
    fi
fi

# Step 5: Start the simulator if requested
echo -e "${YELLOW}Do you want to start the JT808 simulator? (y/n)${NC}"
read -p "" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Starting JT808 simulator...${NC}"
    nohup python simulator.py -v > simulator.log 2>&1 &
    SIMULATOR_PID=$!
    sleep 2
    
    # Check if simulator started successfully
    if ps -p $SIMULATOR_PID > /dev/null; then
        echo -e "${GREEN}✓ JT808 simulator started successfully (PID: $SIMULATOR_PID)${NC}"
        echo -e "${YELLOW}Simulator logs are being written to simulator.log${NC}"
    else
        echo -e "${RED}✗ Failed to start simulator. Check simulator.log for details.${NC}"
    fi
fi

# Step 6: Start MQTT subscriber to monitor messages
echo -e "${YELLOW}Do you want to monitor MQTT messages? (y/n)${NC}"
read -p "" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}Starting MQTT subscriber to monitor messages...${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop monitoring${NC}"
    mosquitto_sub -h localhost -p 1883 -t "pettracker/#" -v
fi

echo -e "${GREEN}✓ Test environment setup complete!${NC}"
echo -e "${YELLOW}To stop the test environment, run: pkill mosquitto; pkill -f 'python converter.py'; pkill -f 'python simulator.py'${NC}"