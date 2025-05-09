# SPDX-License-Identifier: MIT
# Copyright (c) 2016 Adafruit Industries
# Rewritten to use smbus2 by ChatGPT

from __future__ import division
import logging
import time
import math
from smbus2 import SMBus

# I²C default address for the PCA9685
PCA9685_ADDRESS    = 0x40

# Register addresses
MODE1              = 0x00
MODE2              = 0x01
SUBADR1            = 0x02
SUBADR2            = 0x03
SUBADR3            = 0x04
PRESCALE           = 0xFE
LED0_ON_L          = 0x06
LED0_ON_H          = 0x07
LED0_OFF_L         = 0x08
LED0_OFF_H         = 0x09
ALL_LED_ON_L       = 0xFA
ALL_LED_ON_H       = 0xFB
ALL_LED_OFF_L      = 0xFC
ALL_LED_OFF_H      = 0xFD

# Bit masks
RESTART            = 0x80
SLEEP              = 0x10
ALLCALL            = 0x01
INVRT              = 0x10
OUTDRV             = 0x04

logger = logging.getLogger(__name__)

def software_reset(bus_num=1):
    """
    Sends a software reset (SWRST) to all devices on the bus via address 0x00.
    """
    with SMBus(bus_num) as bus:
        # Write single byte 0x06 to device 0x00
        bus.write_byte(0x00, 0x06)


class PCA9685:
    """
    Driver for the PCA9685 16-channel PWM/servo controller using smbus2.
    """
    def __init__(self, bus_num=1, address=PCA9685_ADDRESS):
        """
        bus_num = I²C bus (e.g. on Raspberry Pi, usually 1)
        address = I²C address of the PCA9685 (default 0x40)
        """
        self.address = address
        self.bus = SMBus(bus_num)

        # Reset all PWM channels to off
        self.set_all_pwm(0, 0)

        # Set MODE2 register (output driver)
        self.bus.write_byte_data(self.address, MODE2, OUTDRV)
        # Set MODE1 register (respond to ALLCALL)
        self.bus.write_byte_data(self.address, MODE1, ALLCALL)
        time.sleep(0.005)  # wait for oscillator

        # Wake up (clear sleep bit)
        mode1 = self.bus.read_byte_data(self.address, MODE1)
        mode1 &= ~SLEEP
        self.bus.write_byte_data(self.address, MODE1, mode1)
        time.sleep(0.005)  # wait for oscillator

    def set_pwm_freq(self, freq_hz):
        """
        Set the PWM frequency in hertz.
        """
        prescaleval = 25_000_000.0    # 25 MHz oscillator
        prescaleval /= 4096.0         # 12-bit resolution
        prescaleval /= float(freq_hz)
        prescaleval -= 1.0
        logger.debug(f"Setting PWM frequency to {freq_hz} Hz")
        logger.debug(f"Estimated prescale: {prescaleval}")

        prescale = int(math.floor(prescaleval + 0.5))
        logger.debug(f"Final prescale: {prescale}")

        # Go to sleep to set prescaler
        oldmode = self.bus.read_byte_data(self.address, MODE1)
        newmode = (oldmode & 0x7F) | SLEEP
        self.bus.write_byte_data(self.address, MODE1, newmode)
        # Set the prescaler
        self.bus.write_byte_data(self.address, PRESCALE, prescale)
        # Restore MODE1 and restart
        self.bus.write_byte_data(self.address, MODE1, oldmode)
        time.sleep(0.005)
        self.bus.write_byte_data(self.address, MODE1, oldmode | RESTART)

    def set_pwm(self, channel, on, off):
        """
        Sets a single PWM channel.
        channel = 0..7
        on = tick (0..4095) when signal turns on
        off = tick (0..4095) when signal turns off
        """
        if not 0 <= channel <= 15:
            raise ValueError("Channel must be in [0..15]")
        base = LED0_ON_L + 4 * channel
        self.bus.write_byte_data(self.address, base,     on & 0xFF)
        self.bus.write_byte_data(self.address, base + 1, on >> 8)
        self.bus.write_byte_data(self.address, base + 2, off & 0xFF)
        self.bus.write_byte_data(self.address, base + 3, off >> 8)

    def set_pwm_scaled(self, channel, thrust):
        """
        Sets a single PWM channel scaled.
        channel = 0..7
        thrust = thrust value (-1 to 1) to be converted to ticks
        """

        # Cap thrust to be in range [-1, 1]
        if thrust < -1:
            thrust = -1
        elif thrust > 1:
            thrust = 1

        on = 0
        if thrust < 0:
            off = int((0.076 + thrust * 0.017) * 4095) # These values were determined experimentally
        elif thrust >= 0:
            off = int((0.076 + thrust * 0.019) * 4095) # These values were determined experimentally


        if not 0 <= channel <= 7:
            raise ValueError("Channel must be in [0..7]")
        base = LED0_ON_L + 4 * channel
        self.bus.write_byte_data(self.address, base,     on & 0xFF)
        self.bus.write_byte_data(self.address, base + 1, on >> 8)
        self.bus.write_byte_data(self.address, base + 2, off & 0xFF)
        self.bus.write_byte_data(self.address, base + 3, off >> 8)

    def set_all_pwm(self, on, off):
        """
        Sets all 8 PWM channels to the same on/off ticks.
        """
        self.bus.write_byte_data(self.address, ALL_LED_ON_L,  on & 0xFF)
        self.bus.write_byte_data(self.address, ALL_LED_ON_H,  on >> 8)
        self.bus.write_byte_data(self.address, ALL_LED_OFF_L, off & 0xFF)
        self.bus.write_byte_data(self.address, ALL_LED_OFF_H, off >> 8)

    def close(self):
        """
        Close the underlying I²C bus.
        """
        self.bus.close()


if __name__ == '__main__':
    import time
    
    print("PCA9685 test")
    print("Resetting all PCA9685 devices on bus 1")
    software_reset(bus_num=1)
    
    print("Initializing PCA9685 on bus 1 and setting frequency to 50 Hz")
    pwm = PCA9685(bus_num=1, address=0x40)
    pwm.set_pwm_freq(50)

    print("Initializing all thrusters")
    for i in range(8):
        pwm.set_pwm_scaled(i, 0.0)  # Set all thrusters to 0 thrust

    while True:
        try:
            thruster = int(input("Enter thruster number (0-7)"))
            thrust = float(input("Enter thrust (-1 to 1.0): "))
            
            print(f"Setting thrust for thruster {thruster} to {thrust} for 5 seconds")
            pwm.set_pwm_scaled(thruster, thrust)
            time.sleep(5)
            pwm.set_pwm_scaled(thruster, 0.0)  # Stop the thruster after 5 seconds
            
            print("Thruster stopped")
            print()
            
        except ValueError:
            print("Invalid input, please enter a number between 0.0 and 1.0")
        except KeyboardInterrupt:
            break
    
    pwm.close()