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

        libcamera_cmd = [
            'sudo',
            'libcamera-vid',
            '-t', '0',
            '--width', '1280',
            '--height', '720',
            '--framerate', '30',
            '--codec', 'h264',
            '--bitrate', '4000000',
            '-o', '-'
        ]

        gst_cmd = [
            'sudo',
            'gst-launch-1.0',
            '-v',
            'fdsrc',
            '!',
            'h264parse',
            '!',
            'rtph264pay',
            'config-interval=1',
            'pt=96',
            '!',
            'udpsink',
            f'host={self.ip_address}',
            f'port={self.port}',
            'sync=false',
            'async=false',
            'qos=false'
        ]

        try:
            self.camera_process = subprocess.Popen(
                libcamera_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            self.gst_process = subprocess.Popen(
                gst_cmd,
                stdin=self.camera_process.stdout,
                stderr=subprocess.PIPE
            )

            if self.camera_process.stdout:
                self.camera_process.stdout.close()

            logging.info(f"Stream started successfully. Connect to {self.ip_address}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to start stream: {str(e)}")
            self.stop()
            raise

    def stop(self):
        if hasattr(self, 'gst_process') and self.gst_process:
            self.gst_process.terminate()
            self.gst_process = None
        if hasattr(self, 'camera_process') and self.camera_process:
            self.camera_process.terminate()
            self.camera_process = None
        logging.info("Stream stopped")

    def is_running(self):
        if not hasattr(self, 'camera_process') or not hasattr(self, 'gst_process'):
            return False
        camera_running = self.camera_process and self.camera_process.poll() is None
        gst_running = self.gst_process and self.gst_process.poll() is None
        return camera_running and gst_running
