"""Constants used throughout the firmware."""

# General
FIRMWARE_VERSION = "1.0.0"

# Thruster
INPUT_START_BYTE = 0x5A
NUM_MOTORS = 8
NEUTRAL = 1000
FORWARD_RANGE = 1000
REVERSE_RANGE = 1000
TIMEOUT_MS = 200

# Regulator
COMPLEMENTARY_FILTER_ALPHA = 0.98
DEPTH_DERIVATIVE_EMA_TAU = 0.064

# Toast IDs
THRUSTER_TEST_TOAST_ID = "thruster-test"
AUTO_TUNING_TOAST_ID = "regulator-auto-tuning"
FLASH_TOAST_ID = "flash-microcontroller-firmware"


# Websocket
IP_ADDRESS = "10.10.10.10"
PORT = 9000
