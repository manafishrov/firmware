import ctypes
import time

# Load the shared library (adjust the path if necessary)
lib = ctypes.CDLL("./libmotor-dshot.so")

# Set up the function signatures (no header file needed)
lib.motorImplementationInitialize.argtypes = [
    ctypes.POINTER(ctypes.c_int),  # motorPins[]
    ctypes.c_int                   # motorMax
]
lib.motorImplementationInitialize.restype = None

lib.motorImplementationSendThrottles.argtypes = [
    ctypes.POINTER(ctypes.c_int),   # motorPins[]
    ctypes.c_int,                   # motorMax
    ctypes.POINTER(ctypes.c_double) # motorThrottle[]
]
lib.motorImplementationSendThrottles.restype = None

lib.motorImplementationFinalize.argtypes = [
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int
]
lib.motorImplementationFinalize.restype = None

# Use GPIO pin 19 (using BCM numbering)
motorPins = [19]
motorMax = len(motorPins)
MotorPinsArray = (ctypes.c_int * motorMax)(*motorPins)

# --------------------------------------------------------------------
# 1. Initialize the ESC (this sends a "motor stop" command for ~5 seconds)
lib.motorImplementationInitialize(MotorPinsArray, motorMax)
print("Initializing ESC / Arming, waiting 5 seconds...")

# Arming phase: send 0 throttle repeatedly for 5 seconds
zero_throttle = (ctypes.c_double * motorMax)(*([0.0] * motorMax))
for _ in range(5000):  # 5000 iterations x 1ms ≈ 5 seconds
    lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, zero_throttle)
    time.sleep(0.001)

# --------------------------------------------------------------------
# 2. Spin phase: send 15% throttle continuously for 5 seconds
print("Spinning motor at 15% throttle for 5 seconds...")
spin_throttle = (ctypes.c_double * motorMax)(*([0.15] * motorMax))
for _ in range(5000):  # 5 seconds worth of commands
    lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, spin_throttle)
    time.sleep(0.001)

# --------------------------------------------------------------------
# 3. Stop the motor: send 0 throttle several times
print("Stopping motor...")
for _ in range(100):
    lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, zero_throttle)
    time.sleep(0.001)

# Finalize and clean up
lib.motorImplementationFinalize(MotorPinsArray, motorMax)
print("Finalized and closed the library.")
