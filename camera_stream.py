import subprocess
import signal
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('camera_stream.log')
    ]
)

def get_ip_address():
    """Get the known working IP address"""
    return "169.254.0.2"

def start_stream():
    ip_address = get_ip_address()
    command = [
        'libcamera-vid',
        '-t', '0',
        '--inline',
        '--width', '1280',
        '--height', '720',
        '--framerate', '30',
        '--codec', 'h264',
        '--listen',
        '-o', f'tcp://{ip_address}:5000'
    ]

    logging.info(f"Starting camera stream with command: {' '.join(command)}")
    try:
        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            text=True
        )
        logging.info(f"Stream started successfully. Connect to {ip_address}:5000")
        return process
    except Exception as e:
        logging.error(f"Failed to start stream: {str(e)}")
        raise

if __name__ == '__main__':
    logging.info("Initializing camera stream service")
    stream_process = start_stream()
    
    def signal_handler(*_):
        logging.info("Received shutdown signal")
        stream_process.terminate()
        logging.info("Stream terminated")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    logging.info("Camera stream ready on TCP port 5000")
    signal.pause()
