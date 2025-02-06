import numpy as np
#import RPi.GPIO as GPIO
import socket
import json
import time

# CONFIG VARIABLES
ESC_PINS = [27, 15, 25, 8, 7, 1]  #27 and 15 for single ESCs, 25, 8, 7, 1 for 4x ESC

def setup_thrusters():
    pwms = []
    for pin in ESC_PINS:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.OUT)
        pwm = GPIO.PWM(pin, 50)
        pwm.start(7.5)
        pwms.append(pwm)
    return pwms

def setup_connection():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', 12345))
    print("Socket is set up")
    return s

def get_direction_vector(s):
    #Uses input to make a direction vector containing [forward, side, up, pitch, yaw, roll]
    data, addr = s.recvfrom(1024)
    direction_vector = json.loads(data.decode())
    #Returns first 6 values as one array, last as a single value, the last value is quit value
    return np.array(direction_vector[:6]), direction_vector[6]


def tuning_correction(direction_vector):
    correction_matrix = np.array([[1, 0, 0, 0, 0, 0],
                                  [0, 1, 0, 0, 0, 0],
                                  [0, 0, 1, 0, 0, 0],
                                  [0, 0, 0, 1, 0, 0],
                                  [0, 0, 0, 0, 1, 0],
                                  [0, 0, 0, 0, 0, 1]])
      
    return direction_vector @ correction_matrix

def get_thrust_allocation_matrix():

    # Thruster positions in [x, y, z, pitch, yaw] format
    thrusterPositionMatrix = np.array([[80, 125, -5, (1/3)*np.pi, (1/2)*np.pi], # Right front
                                    [80, -125, -5, (1/3)*np.pi, -(1/2)*np.pi], # Left front
                                    [0, 120, 30, 0, 0], # Right mid
                                    [0, -120, 30, 0, 0], # Left mid
                                    [-80, 125, -5, (1/3)*np.pi, -(1/2)*np.pi], # Right rear
                                    [-80, -125, -5, (1/3)*np.pi, (1/2)*np.pi]]) # Left rear

    centerOfDrag = np.array([0, 0, 0])

    # Creates a new matrix where the positions are relative to the center of drag
    for i in range(thrusterPositionMatrix.shape[0]):
        thrusterPositionMatrix[i, 0] -= centerOfDrag[0]
        thrusterPositionMatrix[i, 1] -= centerOfDrag[1]
        thrusterPositionMatrix[i, 2] -= centerOfDrag[2]

    # Creates force actuation matrix with trigenometry
    pitch = thrusterPositionMatrix[:, 3]
    yaw = thrusterPositionMatrix[:, 4]
    forceActuationMatrix = np.column_stack((np.cos(pitch) * np.cos(yaw), 
                                            np.cos(pitch) * np.sin(yaw), 
                                            np.sin(pitch)))

    # Creates moment actuation matrix using moment arm
    momentActuationMatrix = np.zeros((6, 3))
    for i in range(thrusterPositionMatrix.shape[0]):
        x = thrusterPositionMatrix[i, 0]
        y = thrusterPositionMatrix[i, 1]
        z = thrusterPositionMatrix[i, 2]
        F_x = forceActuationMatrix[i, 0]
        F_y = forceActuationMatrix[i, 1]
        F_z = forceActuationMatrix[i, 2]
        momentActuationMatrix[i] = [-z*F_x + x*F_z, 
                                    -y*F_x - x*F_y, 
                                    -y*F_z]

    # Combines force and moment actuation matrices into a 6x6 matrix
    actuationMatrix = np.column_stack((forceActuationMatrix, momentActuationMatrix))

    # Thrust allocation matrix is the inverse of the transposed actuation matrix, f = A^T*u
    thrustAllocationMatrix = np.linalg.pinv(actuationMatrix.T)

    return thrustAllocationMatrix

def thrust_allocation(input_vector, thrustAllocationMatrix):
    
    thrust_vector = thrustAllocationMatrix @ input_vector

    return thrust_vector

def normalize_thrust_vector(thrust_vector):
    
    # Normalize thrust vector by dividing by the maximum value
    max_thrust = np.max(np.abs(thrust_vector))
    if max_thrust > 0.01:
        thrust_vector /= max_thrust

    return thrust_vector

def linear_ramping(thrust_vector, previous_thrust_vector, ramp_rate):

    difference = thrust_vector - previous_thrust_vector
    difference_norm = np.linalg.norm(difference)
    
    if difference_norm > ramp_rate:
        unity_differece = difference / difference_norm 
        new_thrust_vector = previous_thrust_vector + unity_differece * ramp_rate
    else:
        new_thrust_vector = thrust_vector

    return new_thrust_vector

def set_esc_speed(pwm, speed):

    pwm.ChangeDutyCycle(speed*2.5 + 7.5)

def send_pwm_values(thrust_vector, pwms):
    #TODO: SOMETHING IS WRONG HERE, FIX IT
    for i in range(len(thrust_vector)):
        set_esc_speed(pwms[i], thrust_vector[i])

    print(thrust_vector)

    pass

def cleanup(pwms):
    for pwm in pwms:
        pwm.stop()
    GPIO.cleanup()

def print_thrust_vector(thrust_vector):
    print(f"Thrust vector: {thrust_vector}")



previous_thrust_vector = np.array([0, 0, 0, 0, 0, 0])
s = setup_connection()
thrustAllocationMatrix = get_thrust_allocation_matrix()

while True:
    direction_vector, quit_flag = get_direction_vector(s)

    if quit_flag == 1:
        print("Quit signal received. Exiting.")
        break
    
    direction_vector = tuning_correction(direction_vector)
    
    thrust_vector = thrust_allocation(direction_vector, thrustAllocationMatrix)
    
    thrust_vector = normalize_thrust_vector(thrust_vector)
    
    thrust_vector = linear_ramping(thrust_vector, previous_thrust_vector, 0.1)
    previous_thrust_vector = thrust_vector

    #send_pwm_values(thrust_vector)
    print_thrust_vector(thrust_vector)
    #time.sleep(0.02) # 50 Hz




