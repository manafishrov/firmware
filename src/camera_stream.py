import subprocess
import logging
from .config import get_ip_address, get_camera_port

class CameraStream:
    def __init__(self):
        self.process = None
        self.ip_address = get_ip_address()
        self.port = get_camera_port()

    def start(self):
        if self.process:
            logging.warning("Stream is already running")
            return

        command = [
            'sudo',
            'libcamera-vid',
            '-t', '0',
            '--inline',
            '--width', '1920',
            '--height', '1080',
            '--framerate', '30',
            '--codec', 'h264',
            '--listen',
            '-o', f'tcp://{self.ip_address}:{self.port}'
        ]

        try:
            self.process = subprocess.Popen(
                command,
                stderr=subprocess.PIPE,
                text=True
            )
            logging.info(f"Stream started successfully. Connect to {self.ip_address}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to start stream: {str(e)}")
            raise

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process = None
            logging.info("Stream stopped")
        else:
            logging.warning("No stream to stop")

    def is_running(self):
        return self.process is not None and self.process.poll() is None
