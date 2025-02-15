import ctypes
import time

# 1) Load the shared library (adjust the path if necessary)
lib = ctypes.CDLL("./libmotor-dshot.so")

# 2) Set up the function signatures.
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

# 3) Setup for one motor on GPIO 19 (using BCM numbering)
motorPins = [19]
motorMax = len(motorPins)
MotorPinsArray = (ctypes.c_int * motorMax)(*motorPins)

# Initialize ESC (this sends "motor stop" frames for about 5 seconds)
lib.motorImplementationInitialize(MotorPinsArray, motorMax)
print("ESC Initialized on pin 19.")

# Wait a moment after initialization if needed
time.sleep(2)

# Create a throttle array for one motor.
# For example, 15% throttle (0.15)
throttleValue = 0.15
throttleArray = (ctypes.c_double * motorMax)(*([throttleValue] * motorMax))

# Send throttle commands continuously for 5 seconds.
print("Spinning motor at 50% throttle for 5 seconds...")
end_time = time.time() + 5  # run for 5 seconds
while time.time() < end_time:
    lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, throttleArray)
    # A short sleep (e.g., 1ms) helps mimic the C code loop and avoid hogging the CPU.
    time.sleep(0.001)

# Now stop the motor by sending 0 throttle continuously for a short period.
stopThrottle = 0.0
stopArray = (ctypes.c_double * motorMax)(*([stopThrottle] * motorMax))
print("Stopping motor...")
# Send stop command a few times
for _ in range(100):
    lib.motorImplementationSendThrottles(MotorPinsArray, motorMax, stopArray)
    time.sleep(0.001)

# Finalize and clean up.
lib.motorImplementationFinalize(MotorPinsArray, motorMax)
print("Finalized and closed the library.")
