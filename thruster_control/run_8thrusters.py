import numpy as np
import RPi.GPIO as GPIO
import socket
import json
import time
import dshot_thrust_control as dshot

# CONFIG VARIABLES
ESC_PINS = [26, 19, 13, 6, 25, 8, 7, 1]  #26, 19, 13, 6, for ESC1, 25, 8, 7, 1 for ESC2

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
    correction_matrix = np.array([
        [1, 0, 0, 0, 0, 0],
        [0, 1, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0],
        [0, 0, 0, 1, 0, 0],
        [0, 0, 0, 0, 1, 0],
        [0, 0, 0, 0, 0, 1]
    ])
      
    return direction_vector @ correction_matrix

def get_thrust_allocation_matrix():

    return np.array([
        [1, 1, 0, 0, 1, 0],
        [1, -1, 0, 0, -1, 0],
        [0, 0, 1, -1, 0, 1],
        [0, 0, 1, -1, 0, -1],
        [0, 0, 1, 1, 0, 1],
        [0, 0, 1, 1, 0, -1],
        [-1, 1, 0, 0, -1, 0],
        [-1, -1, 0, 0, 1, 0]])

def thrust_allocation(input_vector, thrustAllocationMatrix):
    
    thrust_vector = thrustAllocationMatrix @ input_vector

    return thrust_vector.astype(np.float64)

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

def print_thrust_vector(thrust_vector):
    print(f"Thrust vector: {thrust_vector}")



previous_thrust_vector = np.array([0, 0, 0, 0, 0, 0, 0, 0])
s = setup_connection()
dshot.setup_thrusters(ESC_PINS)
thrustAllocationMatrix = get_thrust_allocation_matrix()
print("Starting control loop. Press 'esc' to quit.")

while True:
    print("Waiting for input ... ", end="")
    direction_vector, quit_flag = get_direction_vector(s)
    print(f"Received input: {direction_vector}")
    
    if quit_flag == 1:
        print("QUIT SIGNAL RECEIVED. EXITING.")
        break
    
    direction_vector = tuning_correction(direction_vector)
    
    thrust_vector = thrust_allocation(direction_vector, thrustAllocationMatrix)
    
    thrust_vector = normalize_thrust_vector(thrust_vector)
    
    thrust_vector = linear_ramping(thrust_vector, previous_thrust_vector, 0.05)
    previous_thrust_vector = thrust_vector

    dshot.send_thrust_values(thrust_vector)
    print_thrust_vector(thrust_vector)

dshot.cleanup_thrusters()





