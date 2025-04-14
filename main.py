#!/usr/bin/env python3
"""
JT/T 808-2013 GPS Tracking Simulator & MQTT Converter Web Interface

This web interface allows you to start and monitor the simulator and converter.
"""
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
import logging
import os
import json
import threading
import time
import subprocess
import signal

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('jt808-web')

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Global variables to store process states
simulator_process = None
converter_process = None
simulator_log = []
converter_log = []

# Maximum number of log lines to keep
MAX_LOG_LINES = 100

def load_config():
    """Load configuration from file"""
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                return json.load(f)
        else:
            logger.warning("config.json not found, using defaults")
            return {}
    except Exception as e:
        logger.error(f"Failed to load config.json: {e}")
        return {}

def save_config(config):
    """Save configuration to file"""
    try:
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Failed to save config.json: {e}")
        return False

def add_log(log_list, message):
    """Add a log message to the specified log list"""
    log_list.append(message)
    # Keep only the last MAX_LOG_LINES lines
    if len(log_list) > MAX_LOG_LINES:
        log_list.pop(0)

def read_process_output(process, log_list, prefix):
    """Read output from a process and add it to the log list"""
    while process.poll() is None:
        try:
            line = process.stdout.readline().strip()
            if isinstance(line, bytes):
                try:
                    # Try to decode as UTF-8
                    line = line.decode('utf-8')
                except UnicodeDecodeError:
                    # Fall back to latin-1 if UTF-8 fails (it can handle any byte)
                    line = line.decode('latin-1')
            
            if line:
                # Check if the line contains an error message
                if 'Error' in line or 'error' in line or 'Exception' in line or 'exception' in line:
                    add_log(log_list, f"{prefix} ERROR: {line}")
                else:
                    add_log(log_list, f"{prefix}: {line}")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            add_log(log_list, f"{prefix} ERROR: {e}")
            add_log(log_list, f"{prefix} ERROR DETAILS: {error_details}")
            break
    
    # Add a final message when the process exits
    if process.poll() is not None:
        add_log(log_list, f"{prefix}: Process exited with code {process.poll()}")
        
        # Try to capture any remaining output
        remaining_output = ""
        try:
            remaining_output = process.stdout.read()
            if remaining_output:
                if isinstance(remaining_output, bytes):
                    remaining_output = remaining_output.decode('utf-8', errors='replace')
                add_log(log_list, f"{prefix} FINAL OUTPUT: {remaining_output}")
        except Exception as e:
            add_log(log_list, f"{prefix} ERROR reading final output: {e}")

@app.route('/')
def index():
    """Render the main page"""
    config = load_config()
    
    # Prepare data for the template
    data = {
        'simulator_running': simulator_process is not None and simulator_process.poll() is None,
        'converter_running': converter_process is not None and converter_process.poll() is None,
        'simulator_log': simulator_log,
        'converter_log': converter_log,
        'config': config
    }
    
    return render_template('index.html', **data)

@app.route('/mqtt-test')
def mqtt_test():
    """Render the MQTT test page"""
    return render_template('mqtt_test.html')

@app.route('/docs')
def documentation():
    """Render the documentation page"""
    return render_template('documentation.html')

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """API endpoint to get or update configuration"""
    if request.method == 'GET':
        config = load_config()
        return jsonify(config)
    
    elif request.method == 'POST':
        try:
            new_config = request.json
            if save_config(new_config):
                return jsonify({'status': 'success', 'message': 'Configuration saved'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to save configuration'}), 500
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/simulator/start', methods=['POST'])
def api_simulator_start():
    """API endpoint to start the simulator"""
    global simulator_process, converter_process
    
    if simulator_process is not None and simulator_process.poll() is None:
        return jsonify({'status': 'error', 'message': 'Simulator is already running'}), 400
    
    # Check if converter is running
    if converter_process is None or converter_process.poll() is not None:
        add_log(simulator_log, 'Simulator WARNING: MQTT Converter is not running. Start the converter first to avoid connection errors.')
        return jsonify({'status': 'error', 'message': 'MQTT Converter is not running. Please start the converter first.'}), 400
    
    try:
        # Start the simulator process
        simulator_process = subprocess.Popen(
            ['python', 'simulator.py', '-v'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )
        
        # Start a thread to read the process output
        threading.Thread(
            target=read_process_output,
            args=(simulator_process, simulator_log, 'Simulator'),
            daemon=True
        ).start()
        
        add_log(simulator_log, 'Simulator: Process started successfully')
        return jsonify({'status': 'success', 'message': 'Simulator started'})
    except Exception as e:
        add_log(simulator_log, f'Simulator ERROR: Failed to start: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/simulator/stop', methods=['POST'])
def api_simulator_stop():
    """API endpoint to stop the simulator"""
    global simulator_process
    
    if simulator_process is None or simulator_process.poll() is not None:
        return jsonify({'status': 'error', 'message': 'Simulator is not running'}), 400
    
    try:
        # Send termination signal to the process
        simulator_process.terminate()
        
        # Give it some time to terminate gracefully
        timeout = time.time() + 5
        while simulator_process.poll() is None and time.time() < timeout:
            time.sleep(0.1)
            
        # If it's still running, kill it
        if simulator_process.poll() is None:
            simulator_process.kill()
            add_log(simulator_log, 'Simulator: Process killed')
        else:
            add_log(simulator_log, 'Simulator: Process terminated')
            
        simulator_process = None
        return jsonify({'status': 'success', 'message': 'Simulator stopped'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/converter/start', methods=['POST'])
def api_converter_start():
    """API endpoint to start the converter"""
    global converter_process
    
    if converter_process is not None and converter_process.poll() is None:
        return jsonify({'status': 'error', 'message': 'Converter is already running'}), 400
    
    try:
        add_log(converter_log, 'Converter: Starting JT808 to MQTT converter server...')
        
        # Start the converter process
        converter_process = subprocess.Popen(
            ['python', 'converter.py', '-v'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )
        
        # Start a thread to read the process output
        threading.Thread(
            target=read_process_output,
            args=(converter_process, converter_log, 'Converter'),
            daemon=True
        ).start()
        
        add_log(converter_log, 'Converter: Process started successfully')
        add_log(converter_log, 'Converter: You can now start the simulator')
        return jsonify({'status': 'success', 'message': 'Converter started'})
    except Exception as e:
        add_log(converter_log, f'Converter ERROR: Failed to start: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/converter/stop', methods=['POST'])
def api_converter_stop():
    """API endpoint to stop the converter"""
    global converter_process, simulator_process
    
    if converter_process is None or converter_process.poll() is not None:
        return jsonify({'status': 'error', 'message': 'Converter is not running'}), 400
    
    # Check if simulator is still running
    if simulator_process is not None and simulator_process.poll() is None:
        add_log(converter_log, 'Converter WARNING: Simulator is still running. Stop the simulator first to avoid errors.')
        return jsonify({'status': 'error', 'message': 'Simulator is still running. Please stop the simulator first.'}), 400
    
    try:
        # Send termination signal to the process
        converter_process.terminate()
        
        # Give it some time to terminate gracefully
        timeout = time.time() + 5
        while converter_process.poll() is None and time.time() < timeout:
            time.sleep(0.1)
            
        # If it's still running, kill it
        if converter_process.poll() is None:
            converter_process.kill()
            add_log(converter_log, 'Converter: Process killed')
        else:
            add_log(converter_log, 'Converter: Process terminated')
            
        converter_process = None
        return jsonify({'status': 'success', 'message': 'Converter stopped'})
    except Exception as e:
        add_log(converter_log, f'Converter ERROR: Failed to stop: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def api_logs():
    """API endpoint to get the latest logs"""
    return jsonify({
        'simulator_log': simulator_log,
        'converter_log': converter_log
    })

def run_converter_in_background():
    """Run the JT808 converter in the background"""
    try:
        # Import the modules here to avoid circular imports
        import subprocess
        
        # Start the converter process
        global converter_process
        if converter_process is None or converter_process.poll() is not None:
            converter_process = subprocess.Popen(
                ['python', 'converter.py', '-v'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True
            )
            
            # Start a thread to read the process output
            threading.Thread(
                target=read_process_output,
                args=(converter_process, converter_log, 'Converter'),
                daemon=True
            ).start()
            
            add_log(converter_log, 'Converter: Process started automatically by web interface')
            logger.info("JT808 converter started automatically by web interface")
        else:
            logger.info("JT808 converter is already running")
    except Exception as e:
        logger.error(f"Failed to start JT808 converter automatically: {e}")

# Initialize the application on first request
# For newer Flask versions, we use this pattern instead of before_first_request
@app.route('/initialize', methods=['GET'])
def initialize_app():
    """Initialize the application - this is called automatically on first load"""
    logger.info("Initializing the application")
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Run the converter in the background
    run_converter_in_background()
    logger.info("Application initialization complete")
    return jsonify({'status': 'success', 'message': 'Application initialized'})

# Auto-start converter when the application is loaded
with app.app_context():
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Run the converter in the background at startup
    run_converter_in_background()

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # When running directly (not through gunicorn), start the converter immediately
    run_converter_in_background()
    
    app.run(debug=True, host='0.0.0.0', port=8080)