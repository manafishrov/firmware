from flask import Flask, Response
import subprocess

HOST = '0.0.0.0'
PORT = 5009

app = Flask(__name__)

def generate_frames():
    cmd = [
        'libcamera-vid',
        '-t', '0',
        '--width', '1920',
        '--height', '1080',
        '--framerate', '30',
        '--codec', 'mjpeg',
        '--inline',
        '--quality', '85',
        '--brightness', '0.1',
        '--contrast', '1.4',
        '--sharpness', '1.5',
        '--saturation', '1.2',
        '--awb', 'auto',
        '--denoise', 'cdn_off',
        '--output', '-'
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
