import asyncio
import json
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
import cv2
from aiohttp import web
import aiohttp_cors
import logging
from .config import get_ip_address, get_camera_port

class VideoCamera(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        # Try different backend
        self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError("Could not open camera")
        # Lower resolution further
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

def __del__(self):
    if self.cap:
        self.cap.release()

    async def recv(self):
        ret, frame = self.cap.read()
        if not ret:
            return None
        
        # Convert from BGR to RGB
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return VideoFrame.from_ndarray(frame, format="rgb24")

class CameraStream:
    def __init__(self):
        self.app = None
        self.pcs = set()
        self.ip_address = get_ip_address()
        self.port = get_camera_port()

    async def offer_handler(self, request):
        params = await request.json()
        offer = RTCSessionDescription(
            sdp=params["sdp"],
            type=params["type"]
        )

        pc = RTCPeerConnection()
        self.pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc.connectionState == "failed":
                await pc.close()
                self.pcs.discard(pc)

        pc.addTrack(VideoCamera())
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

    async def start(self):
        app = web.Application()
        
        # Setup CORS
        cors = aiohttp_cors.setup(app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods=["POST", "OPTIONS"]
            )
        })

        # Add routes with CORS
        cors.add(app.router.add_post("/offer", self.offer_handler))
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.ip_address, self.port)
        
        try:
            await site.start()
            self.app = app
            logging.info(f"WebRTC server started at http://{self.ip_address}:{self.port}")
        except Exception as e:
            logging.error(f"Failed to start WebRTC server: {str(e)}")
            raise

    async def stop(self):
        # Close all peer connections
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros)
        self.pcs.clear()
        logging.info("WebRTC connections closed")

    def is_running(self):
        return self.app is not None
