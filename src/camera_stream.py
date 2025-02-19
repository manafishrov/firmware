import json
from aiortc import VideoStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaPlayer
from aiohttp import web
import aiohttp_cors
import subprocess
import logging
import socket

# Setup detailed logging
logging.basicConfig(level=logging.DEBUG)

def get_local_ip():
    """Get the local IP address of the machine"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.10.10.1', 1))  # Connect to the network gateway
        local_ip = s.getsockname()[0]
    except:
        local_ip = '10.10.10.10'  # fallback
    finally:
        s.close()
    return local_ip

class CameraStreamTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        command = ['sudo', 'libcamera-vid', '-t', '0', '--width', '1280', '--height', '720', 
                  '--framerate', '30', '--codec', 'h264', '-o', '-']
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE)
        self.camera = MediaPlayer(f'pipe:{self.process.stdout.fileno()}')

    async def recv(self):
        frame = await self.camera.video.recv()
        return frame

    def __del__(self):
        if hasattr(self, 'process'):
            self.process.terminate()
            self.process.wait()

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    
    local_ip = get_local_ip()
    logging.info(f"Local IP address: {local_ip}")
    
    # For local network only, no STUN/TURN servers needed
    config = RTCConfiguration(
        iceServers=[],  # Empty list for local network only
        iceTransportPolicy="all"
    )
    
    pc = RTCPeerConnection(configuration=config)
    
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logging.info(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
        
    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        logging.info(f"ICE connection state is {pc.iceConnectionState}")
        if pc.iceConnectionState == "failed":
            logging.error("ICE connection failed")

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        logging.info(f"ICE gathering state is {pc.iceGatheringState}")

    pc.addTrack(CameraStreamTrack())

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })
    )

app = web.Application()
cors = aiohttp_cors.setup(app)
cors.add(app.router.add_post("/offer", offer), 
        {"*": aiohttp_cors.ResourceOptions(expose_headers="*", allow_headers="*")})

if __name__ == "__main__":
    local_ip = get_local_ip()
    logging.info(f"Starting server on {local_ip}:6900")
    web.run_app(app, host=local_ip, port=6900)
