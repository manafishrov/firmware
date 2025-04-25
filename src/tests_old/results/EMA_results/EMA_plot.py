import pandas as pd
import matplotlib.pyplot as plt

# Load the CSV data
data = pd.read_csv("tests/results/EMA_results/lambda111.csv")

# Create a plot for the filtered pitch derivative over time
plt.figure(figsize=(10, 5))
plt.plot(data["Time (s)"], data["Filtered Derivative Pitch"], label="Filtered Derivative Pitch")
plt.xlabel("Time (s)")
plt.ylabel("Pitch Derivative")
plt.title("Pitch Derivative Over Time")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()
