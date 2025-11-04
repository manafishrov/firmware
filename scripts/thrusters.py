# This script checks sending thruster values and reading telemetry data to/from the Raspberry Pi Pico and its firmware.

import glob
import queue
import struct
import sys
import threading
import time

import serial


TELEMETRY_START_BYTE = 0xA5
TELEMETRY_PACKET_SIZE = 8

INPUT_START_BYTE = 0x5A
INPUT_PACKET_OVERHEAD = 2


current_test_motor_id = -1


def find_pico_port() -> str:
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


def calculate_checksum(data_bytes: bytes | bytearray) -> int:
    checksum = 0
    for byte in data_bytes:
        checksum ^= byte
    return checksum


def send_thrusters(ser_instance: serial.Serial, values: list[int]) -> None:
    assert len(values) == NUM_MOTORS, f"Expected {NUM_MOTORS} values, got {len(values)}"
    data_payload = struct.pack(f"<{NUM_MOTORS}H", *values)
    packet_without_checksum = bytearray([INPUT_START_BYTE]) + data_payload
    checksum = calculate_checksum(packet_without_checksum)
    full_packet = packet_without_checksum + bytearray([checksum])
    ser_instance.write(full_packet)


def print_telemetry(pkt_bytes: bytes | bytearray) -> None:
    global current_test_motor_id

    if len(pkt_bytes) != TELEMETRY_PACKET_SIZE:
        return

    if pkt_bytes[0] != TELEMETRY_START_BYTE:
        return

    calculated_checksum = calculate_checksum(pkt_bytes[0 : TELEMETRY_PACKET_SIZE - 1])
    received_checksum = pkt_bytes[TELEMETRY_PACKET_SIZE - 1]

    if calculated_checksum != received_checksum:
        return

    global_id = pkt_bytes[1]
    packet_type = pkt_bytes[2]

    if packet_type == 0:  # ERPM
        erpm_value = struct.unpack("<i", pkt_bytes[3:7])[0]
        if global_id == current_test_motor_id:
            print(f"[Telemetry] Motor {global_id}: ERPM = {erpm_value}")
    elif packet_type == 1:  # Voltage
        voltage_cv = struct.unpack("<i", pkt_bytes[3:7])[0]
        print(f"[Telemetry] Motor {global_id}: Voltage = {voltage_cv} cV")
    elif packet_type == 2:  # Temperature
        temp_c = struct.unpack("<i", pkt_bytes[3:7])[0]
        print(f"[Telemetry] Motor {global_id}: Temperature = {temp_c} °C")
    elif packet_type == 3:  # Current
        current_ca = struct.unpack("<i", pkt_bytes[3:7])[0]
        print(f"[Telemetry] Motor {global_id}: Current = {current_ca / 100.0:.2f} A")


def telemetry_reader_thread(
    ser_instance: serial.Serial, stop_event: threading.Event, data_queue: queue.Queue
) -> None:
    read_buffer = b""
    print(f"--- Telemetry listener thread started on {ser_instance.port} ---")
    ser_instance.timeout = 0.01

    while not stop_event.is_set():
        try:
            new_bytes = ser_instance.read(ser_instance.in_waiting or 1)
            if new_bytes:
                read_buffer += new_bytes
                while True:
                    start_index = read_buffer.find(bytes([TELEMETRY_START_BYTE]))
                    if start_index == -1:
                        if len(read_buffer) > TELEMETRY_PACKET_SIZE * 2:
                            read_buffer = b""
                        break

                    if start_index > 0:
                        read_buffer = read_buffer[start_index:]

                    if len(read_buffer) >= TELEMETRY_PACKET_SIZE:
                        packet = read_buffer[:TELEMETRY_PACKET_SIZE]
                        data_queue.put(packet)
                        read_buffer = read_buffer[TELEMETRY_PACKET_SIZE:]
                    else:
                        break

            time.sleep(0.001)
        except Exception as e:
            if not stop_event.is_set():
                print(f"Error in telemetry thread: {e}", file=sys.stderr)
            break

    print("--- Telemetry listener thread stopped ---")


def process_queued_telemetry(data_queue: queue.Queue) -> None:
    while not data_queue.empty():
        try:
            pkt = data_queue.get_nowait()
            print_telemetry(pkt)
        except queue.Empty:
            break


def run_test(
    ser_instance: serial.Serial, description: str, values: list[int], duration_s: float
) -> None:
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
    ser_instance: serial.Serial,
    description: str,
    start_val: int,
    end_val: int,
    ramp_duration_s: float,
    hold_duration_s: float,
) -> None:
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
        ser_instance,
        f"Hold at {end_val}",
        [end_val] * NUM_MOTORS,
        hold_duration_s,
    )

    print("    Ramping Down...")
    for i in range(total_ramp_steps + 1):
        progress = i / total_ramp_steps
        current_val = int(end_val - (end_val - start_val) * progress)
        send_thrusters(ser_instance, [current_val] * NUM_MOTORS)
        process_queued_telemetry(telemetry_data_queue)
        time.sleep(SEND_INTERVAL_MS / 1000.0)


def stop_and_pause(ser_instance: serial.Serial, duration_s: float) -> None:
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

        print("\n>>> STATUS: Testing each motor individually with ramped throttles.")
        for i in range(NUM_MOTORS):
            current_test_motor_id = i
            print(f"\n--- Testing Motor {i} ---")

            print(f"\n    Forward Ramp for Motor {i} (50% throttle)")
            for_motor_values = [NEUTRAL] * NUM_MOTORS
            ramp_duration_s = 5
            hold_duration_s = 2
            total_ramp_steps = int(ramp_duration_s * 1000 / SEND_INTERVAL_MS)

            print("        Ramping Up Forward...")
            for step in range(total_ramp_steps + 1):
                progress = step / total_ramp_steps
                val = int(NEUTRAL + (FIFTY_PERCENT_FORWARD - NEUTRAL) * progress)
                for_motor_values[i] = val
                send_thrusters(ser, for_motor_values)
                process_queued_telemetry(telemetry_data_queue)
                time.sleep(SEND_INTERVAL_MS / 1000.0)

            print(
                f"        Holding at {FIFTY_PERCENT_FORWARD} for {hold_duration_s}s..."
            )
            for_motor_values[i] = FIFTY_PERCENT_FORWARD
            run_test(
                ser, f"Hold Motor {i} at 50% Forward", for_motor_values, hold_duration_s
            )

            print("        Ramping Down Forward...")
            for step in range(total_ramp_steps + 1):
                progress = step / total_ramp_steps
                val = int(
                    FIFTY_PERCENT_FORWARD - (FIFTY_PERCENT_FORWARD - NEUTRAL) * progress
                )
                for_motor_values[i] = val
                send_thrusters(ser, for_motor_values)
                process_queued_telemetry(telemetry_data_queue)
                time.sleep(SEND_INTERVAL_MS / 1000.0)
            stop_and_pause(ser, 2)

            print(f"\n    Reverse Ramp for Motor {i} (50% throttle)")
            for_motor_values = [NEUTRAL] * NUM_MOTORS
            total_ramp_steps = int(ramp_duration_s * 1000 / SEND_INTERVAL_MS)

            print("        Ramping Up Reverse...")
            for step in range(total_ramp_steps + 1):
                progress = step / total_ramp_steps
                val = int(NEUTRAL + (FIFTY_PERCENT_REVERSE - NEUTRAL) * progress)
                for_motor_values[i] = val
                send_thrusters(ser, for_motor_values)
                process_queued_telemetry(telemetry_data_queue)
                time.sleep(SEND_INTERVAL_MS / 1000.0)

            print(
                f"        Holding at {FIFTY_PERCENT_REVERSE} for {hold_duration_s}s..."
            )
            for_motor_values[i] = FIFTY_PERCENT_REVERSE
            run_test(
                ser, f"Hold Motor {i} at 50% Reverse", for_motor_values, hold_duration_s
            )

            print("        Ramping Down Reverse...")
            for step in range(total_ramp_steps + 1):
                progress = step / total_ramp_steps
                val = int(
                    FIFTY_PERCENT_REVERSE - (FIFTY_PERCENT_REVERSE - NEUTRAL) * progress
                )
                for_motor_values[i] = val
                send_thrusters(ser, for_motor_values)
                process_queued_telemetry(telemetry_data_queue)
                time.sleep(SEND_INTERVAL_MS / 1000.0)
            stop_and_pause(ser, 2)

        current_test_motor_id = -1
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
            telemetry_thread.join(timeout=2.0)

        if ser and ser.is_open:
            print("Sending final neutral command and closing serial port.")
            try:
                send_thrusters(ser, [NEUTRAL] * NUM_MOTORS)
                time.sleep(0.1)
            except Exception as e:
                print(f"Error sending final neutral command: {e}", file=sys.stderr)
            finally:
                ser.close()

        sys.exit(0)
