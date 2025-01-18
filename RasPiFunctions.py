import RPi.GPIO as GPIO
import time
import socket
import numpy as np

def setup_motors():
    PWM_PINS = [18, 23, 24, 25, 12, 16]
    pwms = []

    GPIO.setmode(GPIO.BCM)
    for pin in PWM_PINS:
        GPIO.setup(pin, GPIO.OUT)
        pwm = GPIO.PWM(pin, 50)
        pwm.start(7.5)
        pwms.append(pwm)

    return pwms

def setup_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', 12345))
    print("Socket is set up")
    return s

def recieve_thrust_vector(s: socket.socket):
    data, addr = s.recvfrom(1024)

    #UNCERTAIN
    thrust_vector = np.frombuffer(data, dtype=np.float64)

    return thrust_vector
    
def convert_to_pwm_percent(thrust_vector: np.array):
    for i in range(len(thrust_vector)):
        thrust_vector[i] = 7.5 + thrust_vector[i]*2.5



def activate_thrusters(thrust_vector_percent, pwms):
    for i in range(len(thrust_vector_percent)):
        pwms[i].ChangeDutyCycle(thrust_vector_percent[i])






















