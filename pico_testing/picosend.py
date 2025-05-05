#This script uses i2c to send thrust values to the pico, that will convert them to PWM signals
# i2c_master.py on the Raspberry Pi

import time, struct
from smbus2 import SMBus

I2C_BUS      = 1
PICO_ADDRESS = 0x10
BUS          = SMBus(I2C_BUS)

def send_thrust(arr):
    """arr: list of 8 ints (−1, 0, 1)"""
    # pack as big-endian signed 16-bit (2 bytes each)
    data = struct.pack('>8h', *arr)
    BUS.write_i2c_block_data(PICO_ADDRESS, 0, list(data))

if __name__ == "__main__":
    try:
        while True:
            # example: all zeros (hover)
            send_thrust([0]*8)
            time.sleep(0.02)
    except KeyboardInterrupt:
        BUS.close()