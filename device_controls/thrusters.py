import numpy as np
import dshot_thrust_control as dshot
from config import get_thruster_magnitude

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

def adjust_magnitude(thrust_vector, magnitude):
    thrust_vector = thrust_vector * magnitude
    return thrust_vector

def print_thrust_vector(thrust_vector):
    print(f"Thrust vector: {thrust_vector}")

def run_thrusters(direction_vector):
    direction_vector = tuning_correction(direction_vector)
    
    thrust_vector = thrust_allocation(direction_vector, thrustAllocationMatrix)
    
    thrust_vector = normalize_thrust_vector(thrust_vector)
    
    thrust_vector = linear_ramping(thrust_vector, previous_thrust_vector, 0.1)

    previous_thrust_vector = thrust_vector

    thrust_vector = adjust_magnitude(thrust_vector, float(get_thruster_magnitude()))

    dshot.send_thrust_values(thrust_vector)


def initialize_thrusters():
    dshot.initialize_thrusters()
    print("Thruster initialization complete!")

# Initialization processes
previous_thrust_vector = np.array([0, 0, 0, 0, 0, 0, 0, 0])
thrustAllocationMatrix = get_thrust_allocation_matrix()
