import numpy as np
import dshot_thrust_control as dshot

import regulator

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

def adjust_magnitude(thrust_vector, magnitude):
    thrust_vector = thrust_vector * magnitude
    return thrust_vector

def correct_spin_direction(thrust_vector):
    spin_directions = np.array([-1, -1, -1, -1, 1, -1, -1, 1])
    thrust_vector = thrust_vector * spin_directions
    return thrust_vector

def print_thrust_vector(thrust_vector):
    print(f"Thrust vector: {thrust_vector}")



def run_thrusters(direction_vector, PID_enabled=False):
    # direction vecor format [forward, side, up, pitch, yaw, roll]

    direction_vector = tuning_correction(direction_vector) # Probably not needed when we have a good PID controller

    if PID_enabled:
        direction_vector = regulator.regulate_pitch_yaw(direction_vector)
            
    thrust_vector = thrust_allocation(direction_vector, thrustAllocationMatrix)
    
    thrust_vector = correct_spin_direction(thrust_vector)

    thrust_vector = adjust_magnitude(thrust_vector, 0.3)
    
    thrust_vector = np.clip(thrust_vector, -1, 1) #Clipping cause the regulator can give values outside of the range [-1, 1]
    dshot.send_thrust_values(thrust_vector)


def initialize_thrusters():
    dshot.setup_thrusters([6, 19, 13, 26, 7, 8, 25, 1])
    print("Thruster initialization complete!")

# Initialization processes
thrustAllocationMatrix = get_thrust_allocation_matrix()
