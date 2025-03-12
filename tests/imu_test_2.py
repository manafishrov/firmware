from monster_imu_file import *
import time

BMI270_1= BMI270(0x68)
BMI270_1.load_config_file()
BMI270_1.set_mode(PERFORMANCE_MODE)
BMI270_1.set_acc_range(ACC_RANGE_2G)
BMI270_1.set_gyr_range(GYR_RANGE_1000)
BMI270_1.set_acc_odr(ACC_ODR_200)
BMI270_1.set_gyr_odr(GYR_ODR_200)
BMI270_1.set_acc_bwp(ACC_BWP_OSR4)
BMI270_1.set_gyr_bwp(GYR_BWP_OSR4)
BMI270_1.disable_fifo_header()
BMI270_1.enable_data_streaming()
BMI270_1.enable_acc_filter_perf()
BMI270_1.enable_gyr_noise_perf()
BMI270_1.enable_gyr_filter_perf()

print("--- IMU initialization finished! ---")

for i in range(100):
    acc_data = BMI270_1.get_acc_data()
    print(acc_data)

    #gyr_data = BMI270_1.get_gyr_data()
    #print(gyr_data)
    
    time.sleep(0.1)

