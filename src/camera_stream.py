import subprocess
import signal
import sys
import logging
from .config import get_ip_address, get_camera_port

def start_stream():
    ip_address = get_ip_address()
    port = get_camera_port()
    command = [
        'libcamera-vid',
        '-t', '0',
        '--inline',
        '--width', '1920',
        '--height', '1080',
        '--framerate', '30',
        '--codec', 'h264',
        '--listen',
        '-o', f'tcp://{ip_address}:{port}'
    ]

    try:
        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            text=True
        )
        logging.info(f"Stream started successfully. Connect to {ip_address}:{port}")
        return process
    except Exception as e:
        logging.error(f"Failed to start stream: {str(e)}")
        raise

if __name__ == '__main__':
    stream_process = start_stream()

    def signal_handler(*_):
        stream_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.pause()
