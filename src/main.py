from .camera_stream import CameraStream
import signal
import asyncio

async def main():
    camera = CameraStream()
    
    def signal_handler(sig, frame):
        print("\nStopping camera stream...")
        asyncio.create_task(camera.stop())
        exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        await camera.start()
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        print(f"Error: {e}")
        await camera.stop()

if __name__ == "__main__":
    asyncio.run(main())
