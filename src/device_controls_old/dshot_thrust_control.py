#!/usr/bin/env python3
import ctypes
import time
import threading

# ----------------------------------------------------------------------
# Load the shared DShot library and set up function prototypes
# ----------------------------------------------------------------------
lib = ctypes.CDLL("./libmotor-dshot.so")

# motorImplementationInitialize(int motorPins[], int motorMax);
lib.motorImplementationInitialize.argtypes = [
    ctypes.POINTER(ctypes.c_int),  # motorPins[]
    ctypes.c_int
]
lib.motorImplementationInitialize.restype = None

# motorImplementationSendThrottles(int motorPins[], int motorMax, double motorThrottle[]);
lib.motorImplementationSendThrottles.argtypes = [
    ctypes.POINTER(ctypes.c_int),  # motorPins[]
    ctypes.c_int,                  # motorMax
    ctypes.POINTER(ctypes.c_double)
]
lib.motorImplementationSendThrottles.restype = None

# motorImplementationFinalize(int motorPins[], int motorMax);
lib.motorImplementationFinalize.argtypes = [
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int
]
lib.motorImplementationFinalize.restype = None

# motorImplementationSet3dModeAndSpinDirection(int motorPins[], int motorMax, int mode3dFlag, int reverseDirectionFlag);
lib.motorImplementationSet3dModeAndSpinDirection.argtypes = [
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
    ctypes.c_int,  # mode3dFlag (1=on, 0=off)
    ctypes.c_int   # reverseDirectionFlag
]
lib.motorImplementationSet3dModeAndSpinDirection.restype = None

# ----------------------------------------------------------------------
# Global variables (used by the background thread)
# ----------------------------------------------------------------------
_thruster_pins = None        # List of GPIO pins for the thrusters.
_motorMax = 0                # Number of thrusters.
_MotorPinsArray = None       # ctypes array of thruster pins.
_current_thrusts = None      # List of current thrust values (one per thruster).
_thrust_lock = threading.Lock()
_sender_running = False
_sender_thread = None

# ----------------------------------------------------------------------
# Internal function: continuously send current thrust values
# ----------------------------------------------------------------------
def _thrust_sender():
    global _current_thrusts, _motorMax, _MotorPinsArray, _sender_running
    while _sender_running:
        # Copy the current thrust values in a thread-safe way.
        with _thrust_lock:
            thrusts = list(_current_thrusts)
        # Create a ctypes array of thrust values.
        thrust_array = (ctypes.c_double * _motorMax)(*thrusts)
        lib.motorImplementationSendThrottles(_MotorPinsArray, _motorMax, thrust_array)
        time.sleep(0.001)  # Send every 1ms

# ----------------------------------------------------------------------
# Function: setup_thrusters(esc_pins)
#
#   Takes a list (or tuple) of up to 8 GPIO pin numbers.
#   Initializes all ESCs, arms them (sends 0 throttle for ~5 sec),
#   sets 3D mode, and starts a background thread that continuously
#   sends DShot signals using the current thrust values.
# ----------------------------------------------------------------------
def setup_thrusters(esc_pins):
    """
    Initialize thrusters on the specified GPIO pins and start the background
    process that continuously sends DShot signals.

    Parameters:
        esc_pins (list[int]): List of up to 8 GPIO pin numbers.
    """
    global _thruster_pins, _motorMax, _MotorPinsArray, _current_thrusts
    global _sender_running, _sender_thread

    if not isinstance(esc_pins, (list, tuple)):
        raise ValueError("esc_pins must be a list or tuple of GPIO pin numbers.")
    if not (1 <= len(esc_pins) <= 8):
        raise ValueError("Provide between 1 and 8 thruster (ESC) pins.")

    _thruster_pins = list(esc_pins)
    _motorMax = len(_thruster_pins)
    _MotorPinsArray = (ctypes.c_int * _motorMax)(*(_thruster_pins))

    # Initialize (arm) the ESCs.
    lib.motorImplementationInitialize(_MotorPinsArray, _motorMax)
    # Arm ESCs: send 0 throttle continuously for 5000 ms.
    zero_array = (ctypes.c_double * _motorMax)(*([0.0] * _motorMax))
    for _ in range(5000):
        lib.motorImplementationSendThrottles(_MotorPinsArray, _motorMax, zero_array)
        time.sleep(0.001)

    # Optionally set 3D mode and spin direction (here: 3D mode on, normal spin).
    lib.motorImplementationSet3dModeAndSpinDirection(_MotorPinsArray, _motorMax, 1, 0)

    # Initialize the thrust vector (start with all zeros).
    _current_thrusts = [0.0] * _motorMax

    # Start the background thread to continuously send thrust values.
    _sender_running = True
    _sender_thread = threading.Thread(target=_thrust_sender, daemon=True)
    _sender_thread.start()

# ----------------------------------------------------------------------
# Function: send_thrust_values(thrust_vector)
#
#   Takes a list of thrust values (one per thruster) where each value is
#   expected to be in the range [-1, 1]. It updates the values that the
#   background thread sends out.
# ----------------------------------------------------------------------
def send_thrust_values(thrust_vector):
    """
    Update the thrust values for each thruster. The background process will
    automatically send these new values via DShot.

    Parameters:
        thrust_vector (list[float]): List of thrust values for each thruster.
                                     Each value should be between -1 and 1.
                                     The length must match the number of thrusters
                                     set up via setup_thrusters().
    """
    global _current_thrusts, _motorMax
    if _current_thrusts is None:
        raise RuntimeError("Thrusters not set up. Call setup_thrusters() first.")
    if len(thrust_vector) != _motorMax:
        raise ValueError(f"Expected thrust_vector of length {_motorMax}, got {len(thrust_vector)}.")

    # Update the thrust values in a thread-safe manner.
    with _thrust_lock:
        _current_thrusts = list(thrust_vector)

# ----------------------------------------------------------------------
# Optional: cleanup_thrusters() can be called to stop the background thread,
# send zero throttle for a short period, and finalize the ESCs.
# ----------------------------------------------------------------------
def cleanup_thrusters():
    """
    Stop sending thrust commands, send zero throttle for a brief period,
    and finalize the thruster hardware.
    """
    global _sender_running, _sender_thread, _MotorPinsArray, _motorMax
    _sender_running = False
    if _sender_thread is not None:
        _sender_thread.join(timeout=1)
    if _MotorPinsArray is not None:
        zero_array = (ctypes.c_double * _motorMax)(*([0.0] * _motorMax))
        for _ in range(2000):
            lib.motorImplementationSendThrottles(_MotorPinsArray, _motorMax, zero_array)
            time.sleep(0.001)
        lib.motorImplementationFinalize(_MotorPinsArray, _motorMax)
