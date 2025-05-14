from thrusters import ThrusterController
from imu import IMU
from regulator import PIDController

import numpy as np
import time

imu = IMU()
thrust_controller = ThrusterController(imu)
regulator = PIDController(imu)

desired_pitch = 0
desired_roll = 0

time.sleep(0.1)

def run_test(desired_pitch, desired_roll):
    last_called_time = time.time()
    
    for i in range(200):
        # Calculate the time delta
        current_time = time.time()
        delta_t = current_time - last_called_time
        last_called_time = current_time

        # Update the IMU readings
        imu.update_pitch_roll()

        # Call the regulator to get the direction vector
        direction_vector = regulator.regulate_to_absolute([0, 0, 0, 0, 0, 0], desired_pitch, desired_roll, delta_t)

        thrust_vector = thrust_controller.thrust_allocation(direction_vector)
        thrust_vector = thrust_controller.correct_spin_direction(thrust_vector)
        thrust_vector = thrust_controller.adjust_magnitude(thrust_vector, 0.3)
        thrust_vector = np.clip(thrust_vector, -1, 1)

        thrust_controller.send_thrust_vector(thrust_vector)

        time.sleep(0.05) # 20Hz

running = True
while running:
    # Ask user if they want to test new PID parameters
    usercontinue = input("Do you want to test new PID parameters? (y/n): ")
    if usercontinue.lower() == "n":
        running = False
        break

    # Get PID values from the user
    Kp_pitch = float(input("Enter K_p_pitch value: "))
    Ki_pitch = float(input("Enter K_i_pitch value: "))
    Kd_pitch = float(input("Enter K_d_pitch value: "))

    Kp_roll = float(input("Enter K_p_roll value: "))
    Ki_roll = float(input("Enter K_i_roll value: "))
    Kd_roll = float(input("Enter K_d_roll value: "))

    # Set the PID values in the regulator
    regulator.set_Kp_pitch(Kp_pitch)
    regulator.set_Ki_pitch(Ki_pitch)
    regulator.set_Kd_pitch(Kd_pitch)
    regulator.set_Kp_roll(Kp_roll)  
    regulator.set_Ki_roll(Ki_roll)
    regulator.set_Kd_roll(Kd_roll)
    
    
    # Get pitch and roll target values
    pitchVal = float(input("Enter pitch value: "))
    rollVal = float(input("Enter roll value: "))

    # Resetting the integrator term in regulator
    regulator.integral_value_pitch = 0
    regulator.integral_value_roll = 0

    # Run the test for 10 seconds
    print("Regulating to specified values for 10 seconds...")
    run_test(pitchVal, rollVal)
    



