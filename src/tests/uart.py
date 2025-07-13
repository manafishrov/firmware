import serial
import struct
import time

UART_PORT = "/dev/serial0"
BAUD = 115200
NUM_MOTORS = 8
PAUSE_DURATION_S = 2

NEUTRAL = 1000
FORWARD_RANGE = 1000
REVERSE_RANGE = 1000

TEN_PERCENT_FORWARD = NEUTRAL + int(FORWARD_RANGE * 0.10)
TWENTY_FIVE_PERCENT_FORWARD = NEUTRAL + int(FORWARD_RANGE * 0.25)

TEN_PERCENT_REVERSE = NEUTRAL - int(REVERSE_RANGE * 0.10)
TWENTY_FIVE_PERCENT_REVERSE = NEUTRAL - int(REVERSE_RANGE * 0.25)


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


def run_test_and_listen(ser, description, values, duration_s):
    print(f"\n>>> STATUS: Running test: '{description}' for {duration_s}s.")
    print(f"    Sending values: {values}")
    send_thrusters(ser, values)

    start_time = time.time()
    while time.time() - start_time < duration_s:
        pkt = ser.read(6)
        if len(pkt) == 6:
            print_telemetry(pkt)


def stop_and_pause(ser, duration_s):
    print(f"\n>>> STATUS: Setting motors to neutral and pausing for {duration_s}s...")
    send_thrusters(ser, [NEUTRAL] * NUM_MOTORS)
    time.sleep(duration_s)


if __name__ == "__main__":
    ser = serial.Serial(UART_PORT, BAUD, timeout=0.1)
    print("--- Starting Thruster Test Sequence (using 0-2000 range) ---")

    run_test_and_listen(
        ser,
        "All motors 10% forward",
        [TEN_PERCENT_FORWARD] * NUM_MOTORS,
        2,
    )
    stop_and_pause(ser, PAUSE_DURATION_S)

    run_test_and_listen(
        ser,
        "All motors 25% forward",
        [TWENTY_FIVE_PERCENT_FORWARD] * NUM_MOTORS,
        2,
    )
    stop_and_pause(ser, PAUSE_DURATION_S)

    run_test_and_listen(
        ser,
        "All motors 10% reverse",
        [TEN_PERCENT_REVERSE] * NUM_MOTORS,
        2,
    )
    stop_and_pause(ser, PAUSE_DURATION_S)

    run_test_and_listen(
        ser,
        "All motors 25% reverse",
        [TWENTY_FIVE_PERCENT_REVERSE] * NUM_MOTORS,
        2,
    )
    stop_and_pause(ser, PAUSE_DURATION_S)

    print("\n>>> STATUS: Testing each motor individually at 25% forward.")
    for i in range(NUM_MOTORS):
        vals = [NEUTRAL] * NUM_MOTORS
        vals[i] = TWENTY_FIVE_PERCENT_FORWARD
        run_test_and_listen(ser, f"Motor {i} only", vals, 1)
        stop_and_pause(ser, 0.5)

    print("\n--- All tests complete. Motors are stopped. ---")
    print("Listening for any final telemetry. Press Ctrl+C to quit.")
    try:
        while True:
            pkt = ser.read(6)
            if len(pkt) == 6:
                print_telemetry(pkt)
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        send_thrusters(ser, [NEUTRAL] * NUM_MOTORS)
        ser.close()
