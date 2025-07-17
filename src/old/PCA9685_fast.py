# optimized_pca9685.py
# SPDX-License-Identifier: MIT
# Copyright (c) 2016 Adafruit Industries
# Rewritten to use smbus2 by ChatGPT
# Now with auto-increment enabled for bulk writes!

from __future__ import division
import time, math, logging
from smbus2 import SMBus

logger = logging.getLogger(__name__)

# I2C default address
PCA9685_ADDRESS = 0x40

# Register addresses
MODE1       = 0x00
MODE2       = 0x01
PRESCALE    = 0xFE
LED0_ON_L   = 0x06

# Mode1 bits
RESTART     = 0x80
SLEEP       = 0x10
AI          = 0x20  # Auto-increment
ALLCALL     = 0x01

# Mode2 bits
OUTDRV      = 0x04

def software_reset(bus_num=1):
    # Broadcast SWRST to 0x00
    with SMBus(bus_num) as bus:
        bus.write_byte(0x00, 0x06)

class PCA9685:
    def __init__(self, bus_num=1, address=PCA9685_ADDRESS):
        self.address = address
        self.bus = SMBus(bus_num)

        # 1) Reset all channels off
        self.set_all_pwm(0, 0)

        # 2) MODE2 = OUTDRV, MODE1 = ALLCALL
        self.bus.write_byte_data(self.address, MODE2, OUTDRV)
        self.bus.write_byte_data(self.address, MODE1, ALLCALL)
        time.sleep(0.005)

        # 3) Wake up (clear SLEEP), enable Auto-Increment
        mode1 = self.bus.read_byte_data(self.address, MODE1)
        mode1 &= ~SLEEP
        mode1 |= AI
        self.bus.write_byte_data(self.address, MODE1, mode1)
        time.sleep(0.005)

    def set_pwm_freq(self, freq_hz):
        prescaleval = 25_000_000.0 / 4096.0 / freq_hz - 1.0
        prescale    = int(math.floor(prescaleval + 0.5))

        oldmode = self.bus.read_byte_data(self.address, MODE1)
        newmode = (oldmode & 0x7F) | SLEEP
        self.bus.write_byte_data(self.address, MODE1, newmode)
        self.bus.write_byte_data(self.address, PRESCALE, prescale)
        self.bus.write_byte_data(self.address, MODE1, oldmode)
        time.sleep(0.005)
        self.bus.write_byte_data(self.address, MODE1, oldmode | RESTART)

    def set_all_pwm(self, on, off):
        # Sets all 16 channels to identical on/off ticks
        self.bus.write_byte_data(self.address, 0xFA, on & 0xFF)
        self.bus.write_byte_data(self.address, 0xFB, on >> 8)
        self.bus.write_byte_data(self.address, 0xFC, off & 0xFF)
        self.bus.write_byte_data(self.address, 0xFD, off >> 8)

    def _compute_off_tick(self, thrust):
        # Ensure we are in the range [-1.0, 1.0]
        t = max(-1.0, min(1.0, thrust))

        # Compute the duty cycle 
        if t > 0:
            duty_cycle = 0.078 + t * (0.016)
        else:
            duty_cycle = 0.076 + t * (0.016)
        
        return int(duty_cycle * 4095)

    def set_all_pwm_scaled(self, thrust_vector):
        # Batch-write channels 0-7 in one I2C transaction
        # Falls back to per-channel on failure
        if len(thrust_vector) != 8:
            raise ValueError("Expected thrust_vector length 8")

        data = []
        for t in thrust_vector:
            off = self._compute_off_tick(t)
            data.extend([
                0        & 0xFF,
                (0 >> 8) & 0xFF,
                off      & 0xFF,
                (off >> 8) & 0xFF,
            ])

        try:
            self.bus.write_i2c_block_data(self.address, LED0_ON_L, data)
        except Exception as e:
            logger.error(f"Bulk write failed: {e}, falling back")
            for ch, t in enumerate(thrust_vector):
                off = self._compute_off_tick(t)
                base = LED0_ON_L + 4 * ch
                tiny = [
                    0        & 0xFF,
                    (0 >> 8) & 0xFF,
                    off      & 0xFF,
                    (off >> 8) & 0xFF,
                ]
                try:
                    self.bus.write_i2c_block_data(self.address, base, tiny)
                except Exception as ex:
                    logger.error(f"Fallback write ch{ch} failed: {ex}")

    def close(self):
        self.bus.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    software_reset()
    pwm = PCA9685(bus_num=1)
    pwm.set_pwm_freq(50)

    print("Testing PCA9685 with all channels")
    print("Setting all channels to 0.0 to initialize ESCs") 
    pwm.set_all_pwm_scaled([0, 0, 0, 0, 0, 0, 0, 0])
    time.sleep(2)

    print()
    print("Going back and forth on interval [-0.1, 0.1] to check deadband and reverse thrust")
    for i in range(3):
        for i in range(-100, 101):
            pwm.set_all_pwm_scaled([i / 1000] * 8)
            time.sleep(0.02)
        for i in range(100, -101, -1):
            pwm.set_all_pwm_scaled([i / 1000] * 8)
            time.sleep(0.02)

    print()
    print("Setting thrusters to -0.2 and 0.2. All thrusters should now spin at the same speed")
    pwm.set_all_pwm_scaled([-0.2, 0.2, -0.2, 0.2, -0.2, 0.2, -0.2, 0.2])
    time.sleep(2)

    print()
    print("Spinning one thruster at a time fast cause it looks cool")
    for j in range(1):
        for i in range(8):
            pwm.set_all_pwm_scaled([0] * 8)
            pwm.set_all_pwm_scaled([0.2 if j == i else 0 for j in range(8)])
            time.sleep(0.2)

    print()
    print("Setting all channels to 0.0 to stop thrusters")
    pwm.set_all_pwm_scaled([0] * 8)

    print("Test over")
    pwm.close()
