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
def send_throttle(throttle_value):
    """
    Send a positive throttle (0.0 <= throttle_value <= 1.0).
    """
    arr = (ctypes.c_double * motorMax)(*([throttle_value] * motorMax))
    lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, arr)


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

    # Phase 1: Spin in normal direction
    print("Sending 3D mode + spin-direction=0...")
    lib.motorImplementationSet3dModeAndSpinDirection(MotorPinsArray, motorMax, 1, 0) #Last argument is the spin direction

    print("Phase 1: Spinning motor  at 15% throttle for 3 seconds, spin-direction = 0...")
    for i in range(3000):
        send_throttle(0.15)
        time.sleep(0.001)

    print("Stopping motor for 2 seconds...")
    send_zero_throttle(2000)

    # Phase 2: Spin in reversed direction
    print("Sending 3D mode + spin-direction=1...")
    lib.motorImplementationSet3dModeAndSpinDirection(MotorPinsArray, motorMax, 1, 1) #Last argument is the spin direction

    print("Phase 2: Spinning motor  at 15% throttle for 3 seconds, spin-direction = 1...")
    for i in range(3000):
        send_throttle(0.15)
        time.sleep(0.001)

    print("Finalizing / closing library...")
    lib.motorImplementationFinalize(MotorPinsArray, motorMax)
    print("Done.")

# -------------------------------------------------
if __name__ == "__main__":
    main()
