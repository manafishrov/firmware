from flask import Flask, Response
import subprocess
import threading

HOST = '0.0.0.0'
PORT = 5009

app = Flask(__name__)

def generate_frames():
    cmd = [
        'libcamera-vid',
        '-t', '0',           # Run indefinitely
        '--width', '1280',
        '--height', '720',
        '--framerate', '30',
        '--codec', 'mjpeg',
        '--inline',          # Output MJPEG
        '--output', '-'      # Output to stdout
    ]
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    
    try:
        while True:
            frame = process.stdout.read(8192)
            if not frame:
                break
            yield frame
    finally:
        process.terminate()

@app.route('/video_feed')
def video_feed():
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

if __name__ == '__main__':
    app.run(host=HOST, port=PORT)
