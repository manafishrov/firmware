import numpy as np
import time

# Custom libraries
import dshot_thrust_control as dshot
import imu
import regulator
import thrusters

imu.init_sensor()
thrust_allocation_matrix = thrusters.get_thrust_allocation_matrix()
thrusters.initialize_thrusters()

running = True
while running:
    # Ask user if they want to test new PID parameters
    usercontinue = input("Do you want to test new PID parameters? (y/n): ")
    if usercontinue.lower() == "n":
        running = False
        break

    # Get PID values from the user
    Kp = float(input("Enter K_p value: "))
    Ki = float(input("Enter K_i value: "))
    Kd = float(input("Enter K_d value: "))

    # Set the PID values in the regulator
    regulator.set_Kp(Kp)
    regulator.set_Ki(Ki)
    regulator.set_Kd(Kd)

    print(f"Current PID values: Kp={regulator.Kp}, Ki={regulator.Ki}, Kd={regulator.Kd}")

    # Get pitch and roll target values
    pitchVal = float(input("Enter pitch value: "))
    rollVal = float(input("Enter roll value: "))

    # Get filename for logging
    filename = input("Enter filename for logging: ")

    print("Regulating to specified values for 8 seconds...")
    direction_vector = np.array([0, 0, 0, 0, 0, 0])
    
    for i in range(400):
        imu.update_pitch_roll()
        imu.log_imu_data(filename)

        direction_vector = regulator.regulate_to_absolute(direction_vector, pitchVal, rollVal)
                
        thrust_vector = thrusters.thrust_allocation(direction_vector, thrust_allocation_matrix)
        
        thrust_vector = thrusters.correct_spin_direction(thrust_vector)

        thrust_vector = thrusters.adjust_magnitude(thrust_vector, 0.3)
        
        # Clipping causes the regulator to give values outside of the range [-1, 1]
        thrust_vector = np.clip(thrust_vector, -1, 1)
        dshot.send_thrust_values(thrust_vector)
        time.sleep(0.02)

    # Stop all thrust for a short period after the run
    for i in range(10):
        dshot.send_thrust_values(np.array([0, 0, 0, 0, 0, 0, 0, 0]))
        time.sleep(0.02)
