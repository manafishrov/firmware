import numpy as np


import regulator
import PCA9685
import config

# PWM DRIVER SETUP

print("Resetting all PCA9685 devices on bus 1")
PCA9685.software_reset(bus_num=1)
prev_thrust_vector = np.zeros(8) # Initialize the previous thrust vector to zero

print("Initializing PCA9685 on bus 1 and setting frequency to 50 Hz")
pwm = PCA9685.PCA9685(bus_num=1, address=0x40)
pwm.set_pwm_freq(50)

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
    # This matrix cannot contain values larger than 1 or smaller than -1
    # Columns represent [forward, side, up, pitch, yaw, roll]
    return np.array([
        [1, 1, 0, 0, 0.25, 0],
        [1, -1, 0, 0, -0.25, 0],
        [0, 0, 1, 1, 0, 1],
        [0, 0, 1, 1, 0, -1],
        [0, 0, 1, -1, 0, 1],
        [0, 0, 1, -1, 0, -1],
        [-1, 1, 0, 0, -0.25, 0],
        [-1, -1, 0, 0, 0.25, 0]])



def thrust_allocation(input_vector, thrustAllocationMatrix): 
    thrust_vector = thrustAllocationMatrix @ input_vector

    return thrust_vector.astype(np.float64)

def adjust_magnitude(thrust_vector, magnitude):
    thrust_vector = thrust_vector * magnitude
    return thrust_vector

def correct_spin_direction(thrust_vector):
    spin_directions = np.array([1, 1, 1, 1, 1, 1, 1, 1])
    thrust_vector = thrust_vector * spin_directions
    return thrust_vector

def remove_deadzone(thrust_vector, deadzone = 0.015):
    for i in range(len(thrust_vector)):
        if abs(thrust_vector[i]) < deadzone:
            thrust_vector[i] = 0
    return thrust_vector

def print_thrust_vector(thrust_vector):
    print(f"Thrust vector: {thrust_vector}")

def send_thrust_vector(thrust_vector):
    if np.array_equal(thrust_vector, prev_thrust_vector):
        return
    else:
        global prev_thrust_vector
        prev_thrust_vector = thrust_vector.copy()
        # This code is probably very inefficient, but it works for now
        pwm.set_pwm_scaled(3, thrust_vector[0])
        pwm.set_pwm_scaled(2, thrust_vector[1])
        pwm.set_pwm_scaled(1, thrust_vector[2])
        pwm.set_pwm_scaled(0, thrust_vector[3])
        pwm.set_pwm_scaled(4, thrust_vector[4])
        pwm.set_pwm_scaled(7, thrust_vector[5])
        pwm.set_pwm_scaled(6, thrust_vector[6])
        pwm.set_pwm_scaled(5, thrust_vector[7])

def run_thrusters(direction_vector, PID_enabled=False):
    # direction vecor format [forward, side, up, pitch, yaw, roll]

    direction_vector = tuning_correction(direction_vector) # Probably not needed when we have a good PID controller

    if PID_enabled:
        direction_vector = regulator.regulate_pitch_roll(direction_vector)
            
    thrust_vector = thrust_allocation(direction_vector, thrustAllocationMatrix)
    
    thrust_vector = correct_spin_direction(thrust_vector)

    thrust_vector = adjust_magnitude(thrust_vector, 0.3)
    
    thrust_vector = np.clip(thrust_vector, -1, 1) #Clipping cause the regulator can give values outside of the range [-1, 1]
    thrust_vector = remove_deadzone(thrust_vector)

    send_thrust_vector(thrust_vector)

# Initialization processes
thrustAllocationMatrix = get_thrust_allocation_matrix()
