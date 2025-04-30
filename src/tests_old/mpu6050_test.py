from mpu6050 import mpu6050
import time

sensor = mpu6050(0x68)

for i in range(100):
    accel_data = sensor.get_accel_data()
    gyro_data = sensor.get_gyro_data()
    temp = sensor.get_temp()

    print(f"Accel data: {accel_data}")
    print(f"Gyro data: {gyro_data}")
    print(f"Temp: {temp}")

    time.sleep(0.1) # 10 Hz