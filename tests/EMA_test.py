import time
import csv
import imu

# Get the EMA parameter from config
EMA_lambda = 0

# Initialize previous IMU readings and filtered derivatives
previous_pitch = None
previous_roll = None
current_dt_pitch = 0.0
current_dt_roll = 0.0

# List to store log entries: [time_offset, filtered_derivative_pitch, filtered_derivative_roll]
log_data = []

start_time = time.time()
last_time = start_time

print("Starting derivative filtering test for 10 seconds...")

imu.init_sensor()

while time.time() - start_time < 10:
    current_time = time.time()
    delta_t = current_time - last_time
    last_time = current_time

    # Get current pitch and roll from the IMU
    imu.update_pitch_roll()
    pitch, roll = imu.get_pitch_roll()

    if previous_pitch is not None:
        # Calculate raw derivatives
        derivative_pitch = (pitch - previous_pitch) / delta_t
        derivative_roll = (roll - previous_roll) / delta_t

        # Apply exponential moving average filtering
        current_dt_pitch = EMA_lambda * current_dt_pitch + (1 - EMA_lambda) * derivative_pitch
        current_dt_roll = EMA_lambda * current_dt_roll + (1 - EMA_lambda) * derivative_roll

        # Log the filtered derivative values with a timestamp (time offset from start)
        log_data.append([current_time - start_time, current_dt_pitch, current_dt_roll])
    else:
        # For the very first reading, log zeros
        log_data.append([current_time - start_time, 0, 0])

    previous_pitch = pitch
    previous_roll = roll

    # Sampling period (adjust as necessary)
    print(f"Measuring, progress: {current_time - start_time:.2f}s")
    time.sleep(0.01)

# Save the logged data to a CSV file
filename = input("Enter filename for logging: ")
with open(f"{filename}.csv", "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["Time (s)", "Filtered Derivative Pitch", "Filtered Derivative Roll"])
    writer.writerows(log_data)

print("Logging complete. Data saved to filtered_derivative_log.csv")
