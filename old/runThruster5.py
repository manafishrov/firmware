import RPi.GPIO as GPIO
import time
import socket


# INTERNET CONFIGURATION
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', 12345))
print("Socket is set up")


# GPIO CONFIGURATION
PWM_PIN = 27
GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, GPIO.OUT)

pwm = GPIO.PWM(PWM_PIN, 50)  # 50 Hz for ESC
current_duty_cycle = 7.5
pwm.start(current_duty_cycle)  # Neutral signal (7.5% duty cycle)
print("PWM is set up!")
    

for i in range(10):
    print("Waiting for message")
    data, addr = s.recvfrom(1024)
    print(f"Received message: {data.decode()}")

    thrust = float(data.decode())

    print("Updating duty cycle")
    thrust_change = thrust - current_duty_cycle
    for i in range(100):
        current_duty_cycle += thrust_change / 100
        pwm.ChangeDutyCycle(current_duty_cycle)  
        time.sleep(0.02)
        print(current_duty_cycle)
        
    print(f"Duty cycle updated, current duty cycle: {current_duty_cycle}")
    
s.close()
pwm.stop()
GPIO.cleanup()
