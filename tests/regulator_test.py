import numpy as np
import time

# Custom libraries
import dshot_thrust_control as dshot
import imu
import regulator
import thrusters

thrust_allocation_matrix = thrusters.get_thrust_allocation_matrix()
thrusters.initialize_thrusters()

running = True
while running:
    usercontinue = input("Do you want to continue? (y/n)")
    if usercontinue == "n":
        running = False
        break

    pitchVal = float(input("Enter pitch value: "))
    rollVal = float(input("Enter roll value: "))

    filename = input("Enter filename for logging: ")

    print("Regulating to specified values for 10 seconds...")
    direction_vector = np.array([0, 0, 0, 0, 0, 0])
    
    # EKSTRASJEKK MED M-DAWG AT FREKVENSEN ER 50HZ
    for i in range(500):
        imu.log_imu_data(filename)

        direction_vector = regulator.regulate_to_absolute(direction_vector, pitchVal, rollVal)
                
        thrust_vector = thrust_allocation(direction_vector, thrustAllocationMatrix)
        
        thrust_vector = correct_spin_direction(thrust_vector)

        thrust_vector = adjust_magnitude(thrust_vector, 0.3)
        
        thrust_vector = np.clip(thrust_vector, -1, 1) #Clipping cause the regulator can give values outside of the range [-1, 1]
        dshot.send_thrust_values(thrust_vector)
        time.sleep(0.02)
