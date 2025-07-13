import serial
import struct
import time
import glob
import sys


def find_pico_port():
    pico_ports = glob.glob("/dev/serial/by-id/usb-Raspberry_Pi_Pico*")
    if not pico_ports:
        pico_ports = glob.glob("/dev/ttyACM*")

    if pico_ports:
        print(f"Found Pico at port: {pico_ports[0]}")
        return pico_ports[0]
    else:
        print("Error: Could not find Raspberry Pi Pico serial port.", file=sys.stderr)
        print("Please ensure the Pico is connected via USB.", file=sys.stderr)
        sys.exit(1)


UART_PORT = find_pico_port()
BAUD = 115200
NUM_MOTORS = 8

NEUTRAL = 1000
FORWARD_RANGE = 1000
REVERSE_RANGE = 1000

TEN_PERCENT_FORWARD = NEUTRAL + int(FORWARD_RANGE * 0.10)
THIRTY_PERCENT_FORWARD = NEUTRAL + int(FORWARD_RANGE * 0.30)
FIFTY_PERCENT_FORWARD = NEUTRAL + int(FORWARD_RANGE * 0.50)
SIXTY_PERCENT_FORWARD = NEUTRAL + int(FORWARD_RANGE * 0.60)

TEN_PERCENT_REVERSE = NEUTRAL - int(REVERSE_RANGE * 0.10)
THIRTY_PERCENT_REVERSE = NEUTRAL - int(REVERSE_RANGE * 0.30)
FIFTY_PERCENT_REVERSE = NEUTRAL - int(REVERSE_RANGE * 0.50)
SIXTY_PERCENT_REVERSE = NEUTRAL - int(REVERSE_RANGE * 0.60)

SEND_INTERVAL_MS = 50


def send_thrusters(ser, values):
    assert len(values) == NUM_MOTORS
    pkt = struct.pack("<8H", *values)
    ser.write(pkt)


def run_test(ser, description, values, duration_s):
    print(f"\n>>> STATUS: Running test: '{description}' for {duration_s}s.")
    print(f"    Sending values: {values}")

    start_time = time.time()
    next_send_time = start_time

    while time.time() - start_time < duration_s:
        now = time.time()

        if now >= next_send_time:
            send_thrusters(ser, values)
            next_send_time = now + (SEND_INTERVAL_MS / 1000.0)

        time.sleep(0.001)


def ramp_test(ser, description, start_val, end_val, ramp_duration_s, hold_duration_s):
    print(
        f"\n>>> STATUS: Running ramp test: '{description}' "
        f"(Ramp: {ramp_duration_s}s, Hold: {hold_duration_s}s)"
    )

    total_ramp_up_steps = int(ramp_duration_s * 1000 / SEND_INTERVAL_MS)
    total_ramp_down_steps = int(ramp_duration_s * 1000 / SEND_INTERVAL_MS)

    print("    Ramping Up...")
    for i in range(total_ramp_up_steps + 1):
        progress = i / total_ramp_up_steps
        current_val = int(start_val + (end_val - start_val) * progress)
        send_thrusters(ser, [current_val] * NUM_MOTORS)
        time.sleep(SEND_INTERVAL_MS / 1000.0)

    print(f"    Holding at {end_val} for {hold_duration_s}s...")
    run_test(ser, f"Hold at {end_val}", [end_val] * NUM_MOTORS, hold_duration_s)

    print("    Ramping Down...")
    for i in range(total_ramp_down_steps + 1):
        progress = i / total_ramp_down_steps
        current_val = int(end_val - (end_val - start_val) * progress)
        send_thrusters(ser, [current_val] * NUM_MOTORS)
        time.sleep(SEND_INTERVAL_MS / 1000.0)


def stop_and_pause(ser, duration_s):
    print(f"\n>>> STATUS: Setting motors to neutral and pausing for {duration_s}s...")
    send_thrusters(ser, [NEUTRAL] * NUM_MOTORS)
    time.sleep(duration_s)


if __name__ == "__main__":
    ser = None
    try:
        ser = serial.Serial(UART_PORT, BAUD, timeout=0)
        print("--- Starting Thruster Control Sequence (via USB serial) ---")

        ramp_test(
            ser,
            "All motors ramp to 50% forward and back",
            NEUTRAL,
            FIFTY_PERCENT_FORWARD,
            ramp_duration_s=5,
            hold_duration_s=10,
        )
        stop_and_pause(ser, 5)

        ramp_test(
            ser,
            "All motors ramp to 50% reverse and back",
            NEUTRAL,
            FIFTY_PERCENT_REVERSE,
            ramp_duration_s=5,
            hold_duration_s=10,
        )
        stop_and_pause(ser, 5)

        print("\n>>> STATUS: Testing each motor individually with stepped throttles.")
        for i in range(NUM_MOTORS):
            print(f"\n--- Testing Motor {i} ---")

            vals_10 = [NEUTRAL] * NUM_MOTORS
            vals_10[i] = TEN_PERCENT_FORWARD
            run_test(ser, f"Motor {i} at 10% forward", vals_10, 5)
            stop_and_pause(ser, 5)

            vals_30 = [NEUTRAL] * NUM_MOTORS
            vals_30[i] = THIRTY_PERCENT_FORWARD
            run_test(ser, f"Motor {i} at 30% forward", vals_30, 5)
            stop_and_pause(ser, 5)

            vals_60 = [NEUTRAL] * NUM_MOTORS
            vals_60[i] = SIXTY_PERCENT_FORWARD
            run_test(ser, f"Motor {i} at 60% forward", vals_60, 5)
            stop_and_pause(ser, 5)

        print("\n--- All tests complete. Motors are stopped. ---")

    except KeyboardInterrupt:
        print("\nControl script interrupted by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}", file=sys.stderr)
    finally:
        if ser and ser.is_open:
            print("Sending final neutral command and closing serial port.")
            send_thrusters(ser, [NEUTRAL] * NUM_MOTORS)
            ser.close()
        sys.exit(0)
