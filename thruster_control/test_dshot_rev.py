import ctypes
import time

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
# 2. Set up the motor pins (BCM numbering). We'll assume one motor on GPIO pin 19.
motorPins = [19]
motorMax = len(motorPins)
MotorPinsArray = (ctypes.c_int * motorMax)(*motorPins)

# -------------------------------------------------
# Helper functions
def send_throttle(throttle_value, duration_ms):
    """
    Send a positive throttle (0.0 <= throttle_value <= 1.0) repeatedly for duration_ms ms.
    """
    arr = (ctypes.c_double * motorMax)(*([throttle_value] * motorMax))
    for _ in range(duration_ms):
        lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, arr)
        time.sleep(0.001)

def send_zero_throttle(duration_ms):
    """Send 0 throttle for duration_ms ms."""
    arr = (ctypes.c_double * motorMax)(*([0.0] * motorMax))
    for _ in range(duration_ms):
        lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, arr)
        time.sleep(0.001)

# -------------------------------------------------
def main():
    print("Initializing (arming) ESC with 0 throttle for ~5 seconds...")
    lib.motorImplementationInitialize(MotorPinsArray, motorMax)
    print("ESC should be armed now (after beeps).")

    # Phase 1: Spin in normal direction (non-3D mode).
    print("Phase 1: Spinning motor in non-3D mode at 15% throttle for 3 seconds...")
    send_throttle(0.15, 3000)
    print("Stopping motor for 2 seconds...")
    send_zero_throttle(2000)

    # Phase 2: Switch to 3D mode, but use the "normal" spin command (flag=0) instead of reversed=1.
    # Some ESCs interpret the flags the opposite way.
    print("Phase 2: Enabling 3D mode, using spin-direction flag=0 (swapped).")
    send_zero_throttle(3000)  # re-arm with zero throttle for 3 seconds

    print("Sending 3D mode + spin-direction=0 repeatedly...")
    for _ in range(10):
        lib.motorImplementationSet3dModeAndSpinDirection(MotorPinsArray, motorMax, 1, 0)
        time.sleep(0.05)

    # Now try spinning at a higher throttle in '3D mode' for 3 seconds
    # If 0.5 is too low, try 0.6 or 0.7
    print("Spinning at 50% throttle for 3 seconds (in swapped 3D mode)...")
    send_throttle(0.5, 3000)

    print("Stopping motor...")
    send_zero_throttle(2000)

    print("Finalizing / closing library...")
    lib.motorImplementationFinalize(MotorPinsArray, motorMax)
    print("Done.")

# -------------------------------------------------
if __name__ == "__main__":
    main()
