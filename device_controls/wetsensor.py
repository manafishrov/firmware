import RPi.GPIO as GPIO
import time

def setup_sensor():
    # Use BCM pin numbering
    GPIO.setmode(GPIO.BCM)

    # Set up the pin as input (no internal pull-up/down resistor)
    GPIO.setup(15, GPIO.IN)


def check_sensor(pin):
    # Read the sensor state: HIGH means wet (moisture detected), LOW means dry
    if GPIO.input(pin) == GPIO.HIGH:
        print("!!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n WATER SENSOR TRIGGERED !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n !!! MOISTURE DETECTED, REMOVE ROV FROM WATER IMMEADIATELY !!! \n")
        return True
    else:
        print("No moisture detected")
        return False

def test():
    pin = setup_sensor()
    try:
        # Call check_sensor() every second
        while True:
            check_sensor(pin)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting program.")
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    test()
