# This script tests that the pressure sensor is working correctly by reading and printing pressure, temperature, and depth data.

import ms5837
import time


def main():
    print("Initializing MS5837 pressure sensor...")
    sensor = ms5837.MS5837_30BA()

    if not sensor.init():
        print("Sensor could not be initialized")
        return

    if not sensor.read():
        print("Sensor read failed!")
        return

    print("\nReading sensor data. Press Ctrl+C to stop.")
    try:
        while True:
            if sensor.read():
                print(
                    ("P: %0.1f mbar\tT: %0.2f C")
                    % (sensor.pressure(), sensor.temperature())
                )
            else:
                print("Sensor read failed!")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nTest ended.")


if __name__ == "__main__":
    main()
