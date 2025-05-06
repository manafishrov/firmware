import serial
import struct
import time

# Open UART on GPIO14 (TX) and GPIO15 (RX) – only TX actually needs to be wired for transmission
ser = serial.Serial('/dev/serial0', baudrate=115200)

def send_thrust(data):

    packet = struct.pack('<f', data)
    ser.write(packet)


if __name__ == '__main__':
    time.sleep(0.1)  

    example_data = 205
    send_thrust(example_data)
    print("Packet sent.")