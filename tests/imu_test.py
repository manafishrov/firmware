import time
import imu

print("Initializing IMU sensor")
imu.init_sensor()

filename = input("Enter filename for logging: ")
print("Measuring IMU for 10 seconds and logging")

for i in range(500):
    data = imu.get_imu_data()
    imu.log_imu_data("IMUTEST_"+filename+".txt")

    if i % 50 == 0:
        print(f"time: {i/50}")

    time.sleep(0.02) # 50 Hz

print("Done logging IMU data")

