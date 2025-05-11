import serial
import struct
import time

# Open UART on GPIO14 (TX) and GPIO15 (RX) – only TX actually needs to be wired for transmission
ser = serial.Serial('/dev/serial0', baudrate=115200)

# 8-byte ASCII header
HEADER = b'MICHFISH'

def send_thrust(data):

    payload = struct.pack('<8f', *data)

    checksum = bytes([sum(payload) & 0xFF])

    packet = HEADER + payload + checksum
    ser.write(packet)


if __name__ == '__main__':
    time.sleep(2)  

    example_data = [0.1, -0.5, 0.9, 0.0, -1.0, 1.0, 0.42, -0.77]
    send_thrust(example_data)
    print("Packet sent.")