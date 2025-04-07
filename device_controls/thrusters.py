import numpy as np
import dshot_thrust_control as dshot

import regulator
import config

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
    spin_directions = np.array([1, -1, -1, 1, 1, -1, -1, -1])
    thrust_vector = thrust_vector * spin_directions
    return thrust_vector

def remove_deadzone(thrust_vector, deadzone = 0.015):
    for i in range(len(thrust_vector)):
        if abs(thrust_vector[i]) < deadzone:
            thrust_vector[i] = 0
    return thrust_vector

def print_thrust_vector(thrust_vector):
    print(f"Thrust vector: {thrust_vector}")



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

    dshot.send_thrust_values(thrust_vector)


def initialize_thrusters():
    dshot.setup_thrusters([config.get_thruster1_pin(), config.get_thruster2_pin(), config.get_thruster3_pin(), config.get_thruster4_pin(), config.get_thruster5_pin(), config.get_thruster6_pin(), config.get_thruster7_pin(), config.get_thruster8_pin()])
    print("Thruster initialization complete!")

# Initialization processes
thrustAllocationMatrix = get_thrust_allocation_matrix()
