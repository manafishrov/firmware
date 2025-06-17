import serial
import struct
import time

UART_PORT = "/dev/serial0"
BAUD = 115200
NUM_MOTORS = 8


def send_thrusters(ser, values):
    assert len(values) == NUM_MOTORS
    pkt = struct.pack("<8H", *values)
    ser.write(pkt)


TELEM_TYPES = ["ERPM", "VOLTAGE", "CURRENT", "TEMPERATURE"]


def print_telemetry(pkt):
    idx = pkt[0]
    typ = pkt[1]
    val = struct.unpack("<i", pkt[2:6])[0]
    if typ < len(TELEM_TYPES):
        tname = TELEM_TYPES[typ]
    else:
        tname = f"UNKNOWN({typ})"
    print(f"TELEMETRY MOTOR {idx}: {tname} = {val}")


if __name__ == "__main__":
    ser = serial.Serial(UART_PORT, BAUD, timeout=0.1)
    print("Testing all motors at once (full power for 2 seconds)...")
    send_thrusters(ser, [1500] * NUM_MOTORS)
    time.sleep(2)
    print("Testing all motors off (neutral for 1 second)...")
    send_thrusters(ser, [0] * NUM_MOTORS)
    time.sleep(1)
    print("Testing each motor individually for 1 second...")
    for i in range(NUM_MOTORS):
        vals = [0] * NUM_MOTORS
        vals[i] = 1500
        send_thrusters(ser, vals)
        time.sleep(1)
    print("Testing two motors at a time (motors 0 and 4, then 1 and 5)...")
    for _ in range(2):
        send_thrusters(ser, [1200, 0, 0, 0, 1200, 0, 0, 0])
        time.sleep(1)
        send_thrusters(ser, [0, 1300, 0, 0, 0, 1300, 0, 0])
        time.sleep(1)
    print("Neutral (off)")
    send_thrusters(ser, [0] * NUM_MOTORS)
    print("Listening for telemetry. Press Ctrl+C to quit.")
    while True:
        pkt = ser.read(6)
        if len(pkt) == 6:
            print_telemetry(pkt)
