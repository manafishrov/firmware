import serial
import struct
import time

# Open UART on GPIO14 (TX) and GPIO15 (RX) – only TX actually needs to be wired for transmission
ser = serial.Serial('/dev/serial0', baudrate=115200)

def send_thrust(data):
    # if len(data) != 8:
    #     print("Data sent to picosend is NOT 8 float values!")

    # for i in range(8):
    #     bytes = float_to_bytes(data[i])

    ser.write(bytes([201]))

def float_to_bytes(value):
    bytes = [0] * 4
    if value < 0:
        value = -value
        bytes[0] = 2
    else:
        bytes[0] = 1
    
    dig1 = value // 0.1
    bytes[1] = int(dig1)
    value = value - dig1*0.1

    dig2 = value // 0.01
    bytes[2] = int(dig2)
    value = value - dig2*0.01

    dig3 = value // 0.001
    bytes[3] = int(dig3)
    value = value - dig3*0.001

    for dig in range(1, 4):
        if bytes[dig] < 0 or bytes[dig] > 9:
            bytes[dig] = 100

    return bytes


if __name__ == '__main__':
    time.sleep(0.5)  

    example_data = [0.1, -0.5, 0.9, 0.0, -1.0, 1.0, 0.42, -0.77]
    send_thrust(example_data)
    print("Packet sent.")