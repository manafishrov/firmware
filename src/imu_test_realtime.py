import time
import imu

print("Initializing IMU sensor")
imu.init_sensor()


for i in range(200):
    imu.update_pitch_roll()
    data = imu.get_pitch_roll()

    print("Pitch: ", data[0], end=" ")
    print("Roll: ", data[1])

    time.sleep(0.1) # 50 Hz

print("Done logging IMU data")

