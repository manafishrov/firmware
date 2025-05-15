import matplotlib.pyplot as plt
import numpy as np

def plot_imu_data(filename):
    pitch = []
    roll = []
    time = []

    # Read and parse the file
    with open(filename, 'r') as f:
        for line in f:
            values = line.strip().split(',')
            if len(values) == 3:
                try:
                    p, r, t = map(float, values)
                    pitch.append(p)
                    roll.append(r)
                    time.append(t)
                except ValueError:
                    continue  # skip lines with invalid data

    if not time:
        print("No data found.")
        return

    # Shift time to start at zero
    time = np.array(time)
    time = time - time[0]

    # Plotting
    plt.figure()
    plt.plot(time, pitch, label='Pitch (°)')
    plt.plot(time, roll, label='Roll (°)')
    plt.xlabel('Time (s)')
    plt.ylabel('Angle (°)')
    plt.title('IMU Pitch and Roll over Time')
    plt.legend()
    plt.grid(True)
    plt.show()

if __name__ == "__main__":
    plot_imu_data("test_results\IMUREADING.txt")
