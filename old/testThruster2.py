import RPi.GPIO as GPIO
import time


# GPIO CONFIGURATION

PWM_PIN = int(input("Enter PWM pin: "))
GPIO.setmode(GPIO.BCM)
GPIO.setup(PWM_PIN, GPIO.OUT)

pwm = GPIO.PWM(PWM_PIN, 50)  # 50 Hz for ESC
current_duty_cycle = 7.5
pwm.start(current_duty_cycle)  # Neutral signal (7.5% duty cycle)
print("PWM is set up!")
    

for i in range(10):
    thrust = float(input("Enter thrust: "))

    pwm.ChangeDutyCycle(thrust)  

pwm.stop()
GPIO.cleanup()
