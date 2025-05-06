# IMPORTANT! THIS FILE NEEDS TO BE NAMED main.py WHEN UPLOADING TO THE PICO, THEN IT WILL RUN AUTOMATICALLY ON BOOTUP.

from machine import UART, Pin, PWM
import struct
import time

PWM_PINS = [0, 2, 6, 8, 10, 12, 14, 16]
pwms = []
for gp in PWM_PINS:
    p = PWM(Pin(gp))
    p.freq(50)
    pwms.append(p)

us_max = 1832
us_mid = 1488
us_min = 1148

uart = UART(1, baudrate=115200, tx=Pin(4), rx=Pin(5))

HEADER = b'MICHFISH'
HEADER_LEN = len(HEADER)
PAYLOAD_LEN = 8 * 4
PACKET_SIZE = HEADER_LEN + PAYLOAD_LEN + 1  # +1 for checksum

buffer = bytearray()

def set_us(pwm, us):
    pwm.duty_u16(int((us/20000)*65535))

def float_to_us(f):
    f = max(min(f, 1.0), -1.0)
    return us_mid + (f * (us_max - us_mid) if f >= 0 else f * (us_mid - us_min))

led = Pin(25, Pin.OUT)
for _ in range(6):
    led.toggle()
    time.sleep(0.5)

while True:
    if uart.any():
        buffer.extend(uart.read())

    while len(buffer) >= PACKET_SIZE:
        if buffer[:HEADER_LEN] == HEADER:
            payload = buffer[HEADER_LEN:HEADER_LEN+PAYLOAD_LEN]
            checksum = buffer[HEADER_LEN+PAYLOAD_LEN]
            if sum(payload) & 0xFF == checksum:
                vals = struct.unpack('<8f', payload)
                print(vals)
                for i, v in enumerate(vals):
                    set_us(pwms[i], float_to_us(v)) #This is where actual call to activate PWMs happens
                led.toggle()
                buffer = buffer[PACKET_SIZE:]
            else:
                buffer = buffer[1:]
        else:
            buffer = buffer[1:]