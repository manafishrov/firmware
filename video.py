from flask import Flask, Response
import picamera
import io
import time

HOST = '0.0.0.0'
PORT = 5009

app = Flask(__name__)

def generate_frames():
    with picamera.PiCamera() as camera:
        camera.resolution = (1280, 720)
        camera.framerate = 30
        camera.start_preview()
        time.sleep(2)  # Camera warm-up
        
        while True:
            stream = io.BytesIO()
            camera.capture(stream, format='jpeg', quality=80, use_video_port=True)
            frame = stream.getvalue()
            stream.seek(0)
            stream.truncate()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host=HOST, port=PORT)
