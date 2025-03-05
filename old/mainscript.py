import numpy as np
import socket
import json
import time

from thruster_control import thrusters
from thruster_control import communication
from thruster_control import dshot_thrust_control as dshot
from thruster_control import wetsensor


# CONFIG VARIABLES
ESC_PINS = [26, 19, 13, 6, 25, 8, 7, 1]  #26, 19, 13, 6, for ESC1, 25, 8, 7, 1 for ESC2


previous_thrust_vector = np.array([0, 0, 0, 0, 0, 0, 0, 0])
s = communication.setup_connection()
dshot.setup_thrusters(ESC_PINS)
thrustAllocationMatrix = thrusters.get_thrust_allocation_matrix()
print("Starting control loop. Press 'esc' to quit.")

while True:
    direction_vector, quit_flag = communication.get_direction_vector(s)  

    if quit_flag == 1:
        print("QUIT SIGNAL RECEIVED. EXITING.")
        break
    
    direction_vector = thrusters.tuning_correction(direction_vector)
    
    thrust_vector = thrusters.thrust_allocation(direction_vector, thrustAllocationMatrix)
    
    thrust_vector = thrusters.normalize_thrust_vector(thrust_vector)
    
    thrust_vector = thrusters.linear_ramping(thrust_vector, previous_thrust_vector, 0.2)

    previous_thrust_vector = thrust_vector

    dshot.send_thrust_values(thrust_vector)
    thrusters.print_thrust_vector(thrust_vector)

    time.sleep(1)

dshot.cleanup_thrusters()





