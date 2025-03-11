import numpy as np
import time
import matplotlib.pyplot as plt

import imu

filename = input("Enter filename for logging: ")
print("Measuring IMU for 10 seconds and logging")

for i in range(500):
    data = imu.get_imu_data()
    imu.log_imu_data("IMUTEST_"+filename)

    if i % 50 == 0:
        print(f"time: {i/10}")

    time.sleep(0.02) # 50 Hz

print("Done logging IMU data")

# Plot the IMU data
data = np.loadtxt("IMUTEST_"+filename, delimiter=",")
plt.plot(data[:, 0], label="Pitch")
plt.plot(data[:, 1], label="Roll")
plt.legend()
plt.show()

                 