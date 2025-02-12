import os
import time
import pigpio

# Launching GPIO library
os.system("sudo pigpiod")  
time.sleep(1)  # Delay to ensure pigpio daemon starts

PIN = 27  # GPIO pin where the ESC/servo is connected

# Initialize pigpio
pi = pigpio.pi()
pi.set_PWM_frequency(PIN, 50)

# Ensure pigpio daemon started correctly
if not pi.connected:
    print("Failed to connect to pigpio daemon. Exiting...")
    exit()

print("Connected to pigpio daemon")

for i in range(15):
    pulsewidth = int(input("Pulsewidth: "))
    pi.set_servo_pulsewidth(PIN, pulsewidth)
    print(f"Freq: {pi.get_PWM_frequency(PIN)}")

# Cleanup
pi.stop()
