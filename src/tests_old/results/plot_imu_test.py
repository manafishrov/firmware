import matplotlib.pyplot as plt
import numpy as np

# Read the file
file_path = "tests/results/Tuning/drytest3.txt"  
pitch, roll, time = [], [], []

with open(file_path, "r") as file:
    for line in file:
        values = line.strip().split(",")
        if len(values) == 3:
            p, r, t = map(float, values)
            pitch.append(p)
            roll.append(r)
            time.append(t)

# Normalize time
time = np.array(time)
time -= time[0]  # Start time at 0

# Plot
plt.figure(figsize=(10, 5))
plt.plot(time, pitch, label="Pitch", color="b")
plt.plot(time, roll, label="Roll", color="r")
plt.xlabel("Time (s)")
plt.ylabel("Angle (degrees)")
plt.title("Pitch and Roll vs. Time")
plt.legend()
plt.grid()
plt.show()
