# picosend_uart.py

import os, termios, struct

# Try these in order until one opens successfully
_PORT_CANDIDATES = ["/dev/serial0", "/dev/ttyAMA0", "/dev/ttyS0"]
_BAUD = termios.B115200  # 115200 baud

def _init_uart():
    for PORT in _PORT_CANDIDATES:
        try:
            fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError:
            continue

        # Get current attributes
        attrs = termios.tcgetattr(fd)
        # attrs = [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]

        # Raw mode: no parity, 8 bits, enable read, local mode
        attrs[0] = termios.IGNPAR          # iflag
        attrs[1] = 0                       # oflag
        attrs[2] = _BAUD | termios.CS8 | termios.CLOCAL | termios.CREAD  # cflag
        attrs[3] = 0                       # lflag

        # Directly set input/output speeds
        attrs[4] = _BAUD  # ispeed
        attrs[5] = _BAUD  # ospeed

        # VMIN=1, VTIME=0
        attrs[6][termios.VMIN]  = 1
        attrs[6][termios.VTIME] = 0

        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        print(f"Opened UART on {PORT}")
        return fd

    raise FileNotFoundError(
        "Could not open any of: " + ", ".join(_PORT_CANDIDATES)
    )

# Open and configure UART once at import time
_fd = _init_uart()

def send_thrust(values):
    if len(values) != 8:
        raise ValueError("Must send exactly 8 values")
    # Clamp to [-1.0, +1.0]
    clamped = [max(min(float(v), 1.0), -1.0) for v in values]
    packet = b'\xAA\x55' + struct.pack('>8f', *clamped)
    os.write(_fd, packet)
