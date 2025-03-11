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

def normalize_thrust_vector(thrust_vector):
    
    # Normalize thrust vector by dividing by the maximum value, unused
    max_thrust = np.max(np.abs(thrust_vector))
    if max_thrust > 0.01:
        thrust_vector /= max_thrust

    return thrust_vector

def linear_ramping(thrust_vector, previous_thrust_vector, ramp_rate):
    # Unused
    difference = thrust_vector - previous_thrust_vector
    difference_norm = np.linalg.norm(difference)
    
    if difference_norm > ramp_rate:
        unity_differece = difference / difference_norm 
        new_thrust_vector = previous_thrust_vector + unity_differece * ramp_rate
    else:
        new_thrust_vector = thrust_vector

    return new_thrust_vector

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
