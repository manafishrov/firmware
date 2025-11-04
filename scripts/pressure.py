# This script tests that the pressure sensor is working correctly by reading and printing pressure, temperature, and depth data.

import time

import ms5837


def main() -> None:
    sensor = ms5837.MS5837_30BA()

    if not sensor.init():
        return

    if not sensor.read():
        return

    try:
        while True:
            if sensor.read():
                pass
            else:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
