import serial
import struct
import time
import glob
import sys
import threading
import queue


def find_pico_port():
    pico_ports = glob.glob("/dev/serial/by-id/usb-Raspberry_Pi_Pico*")
    if not pico_ports:
        pico_ports = glob.glob("/dev/ttyACM*")

    if pico_ports:
        print(f"Found Pico at port: {pico_ports[0]}")
        return pico_ports[0]
    else:
        print("Error: Could not find Raspberry Pi Pico serial port.", file=sys.stderr)
        print(
            "Please ensure the Pico is connected via USB and running the firmware.",
            file=sys.stderr,
        )
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

TELEM_TYPES = ["ERPM", "VOLTAGE", "CURRENT", "TEMPERATURE"]
TELEMETRY_PACKET_SIZE = 6


def send_thrusters(ser_instance, values):
    assert len(values) == NUM_MOTORS, f"Expected {NUM_MOTORS} values, got {len(values)}"
    pkt = struct.pack("<8H", *values)
    ser_instance.write(pkt)


def print_telemetry(pkt_bytes):
    if len(pkt_bytes) != TELEMETRY_PACKET_SIZE:
        print(
            f"Warning: Received malformed telemetry packet size {len(pkt_bytes)}: {pkt_bytes.hex()}",
            file=sys.stderr,
        )
        return

    motor_idx = pkt_bytes[0]
    telem_type_code = pkt_bytes[1]
    value = struct.unpack("<i", pkt_bytes[2:6])[0]

    telem_type_name = (
        TELEM_TYPES[telem_type_code]
        if telem_type_code < len(TELEM_TYPES)
        else f"UNKNOWN_TYPE({telem_type_code})"
    )
    print(f"[Telemetry] Motor {motor_idx}: {telem_type_name} = {value}")


def telemetry_reader_thread(ser_instance, stop_event, data_queue):
    read_buffer = b""
    print(f"--- Telemetry listener thread started on {ser_instance.port} ---")
    ser_instance.timeout = 0.01  # 10ms timeout

    while not stop_event.is_set():
        try:
            new_bytes = ser_instance.read(ser_instance.in_waiting or 1)
            if new_bytes:
                read_buffer += new_bytes
                while len(read_buffer) >= TELEMETRY_PACKET_SIZE:
                    packet = read_buffer[:TELEMETRY_PACKET_SIZE]
                    data_queue.put(packet)
                    read_buffer = read_buffer[TELEMETRY_PACKET_SIZE:]

            time.sleep(0.001)
        except Exception as e:
            if not stop_event.is_set():
                print(f"Error in telemetry thread: {e}", file=sys.stderr)
            break

    print("--- Telemetry listener thread stopped ---")


def process_queued_telemetry(data_queue):
    while not data_queue.empty():
        try:
            pkt = data_queue.get_nowait()
            print_telemetry(pkt)
        except queue.Empty:
            break


def run_test(ser_instance, description, values, duration_s):
    print(f"\n>>> STATUS: Running test: '{description}' for {duration_s}s.")
    print(f"    Sending values: {values}")

    start_time = time.time()
    next_send_time = start_time

    while time.time() - start_time < duration_s:
        now = time.time()
        if now >= next_send_time:
            send_thrusters(ser_instance, values)
            next_send_time = now + (SEND_INTERVAL_MS / 1000.0)

        process_queued_telemetry(telemetry_data_queue)
        time.sleep(0.001)


def ramp_test(
    ser_instance, description, start_val, end_val, ramp_duration_s, hold_duration_s
):
    print(
        f"\n>>> STATUS: Running ramp test: '{description}' (Ramp: {ramp_duration_s}s, Hold: {hold_duration_s}s)"
    )
    total_ramp_steps = int(ramp_duration_s * 1000 / SEND_INTERVAL_MS)

    print("    Ramping Up...")
    for i in range(total_ramp_steps + 1):
        progress = i / total_ramp_steps
        current_val = int(start_val + (end_val - start_val) * progress)
        send_thrusters(ser_instance, [current_val] * NUM_MOTORS)
        process_queued_telemetry(telemetry_data_queue)
        time.sleep(SEND_INTERVAL_MS / 1000.0)

    print(f"    Holding at {end_val} for {hold_duration_s}s...")
    run_test(
        ser_instance, f"Hold at {end_val}", [end_val] * NUM_MOTORS, hold_duration_s
    )

    print("    Ramping Down...")
    for i in range(total_ramp_steps + 1):
        progress = i / total_ramp_steps
        current_val = int(end_val - (end_val - start_val) * progress)
        send_thrusters(ser_instance, [current_val] * NUM_MOTORS)
        process_queued_telemetry(telemetry_data_queue)
        time.sleep(SEND_INTERVAL_MS / 1000.0)


def stop_and_pause(ser_instance, duration_s):
    """Sets motors to neutral and pauses, processing telemetry during the pause."""
    print(f"\n>>> STATUS: Setting motors to neutral and pausing for {duration_s}s...")
    send_thrusters(ser_instance, [NEUTRAL] * NUM_MOTORS)
    start_time = time.time()
    while time.time() - start_time < duration_s:
        process_queued_telemetry(telemetry_data_queue)
        time.sleep(0.001)


if __name__ == "__main__":
    ser = None
    telemetry_thread = None
    telemetry_thread_stop_event = threading.Event()
    telemetry_data_queue = queue.Queue()

    try:
        ser = serial.Serial(UART_PORT, BAUD)
        print("--- Starting Thruster Control Sequence with Telemetry Listener ---")

        telemetry_thread = threading.Thread(
            target=telemetry_reader_thread,
            args=(ser, telemetry_thread_stop_event, telemetry_data_queue),
        )
        telemetry_thread.daemon = True
        telemetry_thread.start()
        time.sleep(0.1)

        ramp_test(
            ser,
            "All motors ramp to 50% forward and back",
            NEUTRAL,
            FIFTY_PERCENT_FORWARD,
            5,
            10,
        )
        stop_and_pause(ser, 5)
        ramp_test(
            ser,
            "All motors ramp to 50% reverse and back",
            NEUTRAL,
            FIFTY_PERCENT_REVERSE,
            5,
            10,
        )
        stop_and_pause(ser, 5)

        print("\n>>> STATUS: Testing each motor individually with stepped throttles.")
        for i in range(NUM_MOTORS):
            print(f"\n--- Testing Motor {i} ---")
            run_test(
                ser,
                f"Motor {i} at 10% forward",
                [NEUTRAL] * i
                + [TEN_PERCENT_FORWARD]
                + [NEUTRAL] * (NUM_MOTORS - 1 - i),
                5,
            )
            stop_and_pause(ser, 5)
            run_test(
                ser,
                f"Motor {i} at 30% forward",
                [NEUTRAL] * i
                + [THIRTY_PERCENT_FORWARD]
                + [NEUTRAL] * (NUM_MOTORS - 1 - i),
                5,
            )
            stop_and_pause(ser, 5)
            run_test(
                ser,
                f"Motor {i} at 60% forward",
                [NEUTRAL] * i
                + [SIXTY_PERCENT_FORWARD]
                + [NEUTRAL] * (NUM_MOTORS - 1 - i),
                5,
            )
            stop_and_pause(ser, 5)

        print("\n--- All tests complete. Motors are stopped. ---")

    except KeyboardInterrupt:
        print("\nControl script interrupted by user. Shutting down gracefully...")
    except serial.SerialException as e:
        print(f"\nSerial port error: {e}", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
    finally:
        if telemetry_thread and telemetry_thread.is_alive():
            telemetry_thread_stop_event.set()
            telemetry_thread.join(timeout=1.0)

        if ser and ser.is_open:
            print("Sending final neutral command and closing serial port.")
            send_thrusters(ser, [NEUTRAL] * NUM_MOTORS)
            ser.close()

        sys.exit(0)
