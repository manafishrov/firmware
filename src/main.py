from .camera_stream import CameraStream

def main():
    camera = CameraStream()

    camera.start()

if __name__ == "__main__":
    main()
