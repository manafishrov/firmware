#!/usr/bin/env python3
import ctypes
import time
import threading

# -------------------------------------------------
# 1. Load the shared library and define function prototypes
lib = ctypes.CDLL("./libmotor-dshot.so")

# void motorImplementationInitialize(int motorPins[], int motorMax);
lib.motorImplementationInitialize.argtypes = [
    ctypes.POINTER(ctypes.c_int),  # motorPins[]
    ctypes.c_int
]
lib.motorImplementationInitialize.restype = None

# void motorImplementationSendThrottles(int motorPins[], int motorMax, double motorThrottle[]);
lib.motorImplementationSendThrottles.argtypes = [
    ctypes.POINTER(ctypes.c_int),  # motorPins[]
    ctypes.c_int,                  # motorMax
    ctypes.POINTER(ctypes.c_double)
]
lib.motorImplementationSendThrottles.restype = None

# void motorImplementationFinalize(int motorPins[], int motorMax);
lib.motorImplementationFinalize.argtypes = [
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int
]
lib.motorImplementationFinalize.restype = None

# void motorImplementationSet3dModeAndSpinDirection(int motorPins[], int motorMax,
#                                                   int mode3dFlag, int reverseDirectionFlag);
lib.motorImplementationSet3dModeAndSpinDirection.argtypes = [
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
    ctypes.c_int,  # mode3dFlag (1=3D on, 0=off)
    ctypes.c_int   # reverseDirectionFlag
]
lib.motorImplementationSet3dModeAndSpinDirection.restype = None

# -------------------------------------------------
# 2. Define helper functions for DShot motor control.
#    These functions now take MotorPinsArray and motorMax as parameters.

def send_throttle(MotorPinsArray, motorMax, throttle_value):
    """
    Send a throttle command (between -1.0 and 1.0) to all motors.
    """
    arr = (ctypes.c_double * motorMax)(*([throttle_value] * motorMax))
    lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, arr)

def send_zero_throttle(MotorPinsArray, motorMax, duration_ms):
    """
    Send 0 throttle for duration_ms milliseconds.
    """
    arr = (ctypes.c_double * motorMax)(*([0.0] * motorMax))
    for _ in range(duration_ms):
        lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, arr)
        time.sleep(0.001)

def ramp_dshot(MotorPinsArray, motorMax, start, end, step=0.05, hold_time=0.5):
    """
    Gradually change the throttle from start to end.
    At each step the current throttle is sent continuously for hold_time seconds.
    """
    current = start
    if start < end:
        while current < end:
            current = min(current + step, end)
            end_time = time.time() + hold_time
            while time.time() < end_time:
                send_throttle(MotorPinsArray, motorMax, current)
                time.sleep(0.001)
            print(f"Throttle: {current}")
    else:
        while current > end:
            current = max(current - step, end)
            end_time = time.time() + hold_time
            while time.time() < end_time:
                send_throttle(MotorPinsArray, motorMax, current)
                time.sleep(0.001)
            print(f"Throttle: {current}")
    return end

# -------------------------------------------------
# 3. Define test functions.

def automatic_test(pin):
    """
    Automatic test:
      - Initialize (arm) the ESC with 0 throttle for ~5 sec.
      - Hold neutral throttle (0.0) for 5 sec.
      - Ramp throttle from 0.0 to 0.15, then from 0.15 to -0.15, then back to 0.0.
      - Finally, send 0 throttle for 2 sec and finalize.
    """
    print(f"\nStarting automatic test on motor at GPIO pin {pin} (DShot mode)...")
    motorPins = [pin]
    motorMax = len(motorPins)
    MotorPinsArray = (ctypes.c_int * motorMax)(*motorPins)

    print("Initializing (arming) ESC with 0 throttle for ~5 seconds...")
    lib.motorImplementationInitialize(MotorPinsArray, motorMax)
    send_zero_throttle(MotorPinsArray, motorMax, 5000)
    print("ESC armed (after beeps).")

    print("Setting 3D mode with spin-direction=0...")
    lib.motorImplementationSet3dModeAndSpinDirection(MotorPinsArray, motorMax, 1, 0)

    neutral = 0.0
    print("Holding neutral throttle (0.0) for 5 seconds...")
    end_time = time.time() + 5
    while time.time() < end_time:
        send_throttle(MotorPinsArray, motorMax, neutral)
        time.sleep(0.001)

    print("Ramping up from 0.0 to 0.15 throttle...")
    ramp_dshot(MotorPinsArray, motorMax, 0.0, 0.15)

    print("Ramping down from 0.15 to -0.15 throttle...")
    ramp_dshot(MotorPinsArray, motorMax, 0.15, -0.15)

    print("Ramping up from -0.15 to 0.0 throttle...")
    ramp_dshot(MotorPinsArray, motorMax, -0.15, 0.0)

    print("Stopping motor for 2 seconds...")
    send_zero_throttle(MotorPinsArray, motorMax, 2000)
    lib.motorImplementationFinalize(MotorPinsArray, motorMax)
    print(f"Automatic test on motor at GPIO pin {pin} completed.\n")

def manual_test(pin):
    """
    Manual test:
      - Initialize (arm) the ESC with 0 throttle for ~5 sec.
      - Set 3D mode.
      - Start a background thread that continuously sends the current throttle value.
      - Allow the user to update the throttle value (between -1 and 1) interactively.
      - When quitting, stop the motor and finalize.
    """
    print(f"\nStarting manual test on motor at GPIO pin {pin} (DShot mode)...")
    motorPins = [pin]
    motorMax = len(motorPins)
    MotorPinsArray = (ctypes.c_int * motorMax)(*motorPins)

    print("Initializing (arming) ESC with 0 throttle for ~5 seconds...")
    lib.motorImplementationInitialize(MotorPinsArray, motorMax)
    send_zero_throttle(MotorPinsArray, motorMax, 5000)
    print("ESC armed (after beeps).")

    print("Setting 3D mode with spin-direction=0...")
    lib.motorImplementationSet3dModeAndSpinDirection(MotorPinsArray, motorMax, 1, 0)

    # Set up a shared variable and a lock for the current throttle.
    current_throttle = 0.0
    throttle_lock = threading.Lock()
    running = True

    def throttle_sender():
        while running:
            with throttle_lock:
                val = current_throttle
            send_throttle(MotorPinsArray, motorMax, val)
            time.sleep(0.001)  # Send command every 1ms

    sender_thread = threading.Thread(target=throttle_sender)
    sender_thread.daemon = True
    sender_thread.start()

    try:
        while True:
            user_input = input("Enter a throttle value between -1 and 1 (or type 'q' to quit manual test): ")
            if user_input.lower() == 'q':
                break
            try:
                throttle = float(user_input)
            except ValueError:
                print("Invalid input. Please enter a number between -1 and 1 or 'q' to quit.")
                continue
            if throttle < -1 or throttle > 1:
                print("Throttle value out of range. Please enter a number between -1 and 1.")
                continue
            with throttle_lock:
                current_throttle = throttle
            print(f"Throttle set to {throttle}")
    finally:
        running = False
        sender_thread.join(timeout=1)
        print("Stopping motor...")
        send_zero_throttle(MotorPinsArray, motorMax, 2000)
        lib.motorImplementationFinalize(MotorPinsArray, motorMax)
        print(f"Manual test on motor at GPIO pin {pin} completed.\n")

def test_propeller(pin):
    """
    Test Propeller mode:
      - Initialize (arm) the ESC with 0 throttle for ~5 sec.
      - Set 3D mode.
      - For each throttle level in the sequence:
            0, 0.2, 0.4, 0.6, 0.8, 1, 0, -0.2, -0.4, -0.6, -0.8, -1,
        continuously send the throttle command for 10 seconds.
      - Print informative messages for each level.
      - Finally, send 0 throttle for 2 sec and finalize.
    """
    print(f"\nStarting propeller test on motor at GPIO pin {pin} (DShot mode)...")
    motorPins = [pin]
    motorMax = len(motorPins)
    MotorPinsArray = (ctypes.c_int * motorMax)(*motorPins)

    print("Initializing (arming) ESC with 0 throttle for ~5 seconds...")
    lib.motorImplementationInitialize(MotorPinsArray, motorMax)
    send_zero_throttle(MotorPinsArray, motorMax, 5000)
    print("ESC armed (after beeps).")

    print("Setting 3D mode with spin-direction=0...")
    lib.motorImplementationSet3dModeAndSpinDirection(MotorPinsArray, motorMax, 1, 0)

    # Define the throttle sequence.
    throttle_sequence = [0, 0.2, 0.4, 0.6, 0.8, 1, 0, -0.2, -0.4, -0.6, -0.8, -1]
    
    for throttle in throttle_sequence:
        print(f"\nCurrent throttle: {throttle}")
        end_time = time.time() + 10
        while time.time() < end_time:
            send_throttle(MotorPinsArray, motorMax, throttle)
            time.sleep(0.001)
    
    print("\nPropeller test complete. Stopping motor for 2 seconds...")
    send_zero_throttle(MotorPinsArray, motorMax, 2000)
    lib.motorImplementationFinalize(MotorPinsArray, motorMax)
    print(f"Propeller test on motor at GPIO pin {pin} completed.\n")

# -------------------------------------------------
# 4. Main program loop

def main():
    while True:
        pin_input = input("Enter the GPIO pin to test (or type 'q' to quit): ")
        if pin_input.lower() == 'q':
            break
        try:
            pin = int(pin_input)
        except ValueError:
            print("Invalid GPIO pin number. Please enter an integer.")
            continue

        mode = input("Select test mode - automatic (a), manual (m), or propeller test (t): ").lower()
        if mode == 'a':
            automatic_test(pin)
        elif mode == 'm':
            manual_test(pin)
        elif mode == 't':
            test_propeller(pin)
        else:
            print("Invalid selection. Please choose 'a' for automatic, 'm' for manual, or 't' for propeller test.")
    print("Exiting program.")

if __name__ == '__main__':
    main()
