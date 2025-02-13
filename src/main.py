from .camera_stream import CameraStream
import signal
import time

def main():
    camera = CameraStream()
    def signal_handler(sig, frame):
        print("\nStopping camera stream...")
        camera.stop()
        exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    try:
        camera.start()
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"Error: {e}")
        camera.stop()

if __name__ == "__main__":
    main()
