import RPi.GPIO as GPIO
import time

def ramp_pwm(pwm, start, end, step=0.05, delay=0.1):
    """Gradually change the PWM duty cycle from start to end."""
    current = start
    if start < end:
        while current < end:
            current = min(current + step, end)
            pwm.ChangeDutyCycle(current)
            time.sleep(delay)
    else:
        while current > end:
            current = max(current - step, end)
            pwm.ChangeDutyCycle(current)
            time.sleep(delay)
    return end

def automatic_test(pin):
    """Automatic test: Hold 7.5% for 5 sec, ramp up to 9, down to 6, and back to 7.5."""
    print(f"\nStarting automatic test on GPIO pin {pin}...")
    GPIO.setup(pin, GPIO.OUT)
    pwm = GPIO.PWM(pin, 50)  # 50Hz PWM signal
    pwm.start(7.5)
    
    print("Setting duty cycle to 7.5% and waiting for 20 seconds...")
    time.sleep(20)
    
    print("Ramping up from 7.5% to 9%...")
    ramp_pwm(pwm, 7.5, 9.0)
    
    print("Ramping down from 9% to 6%...")
    ramp_pwm(pwm, 9.0, 6.0)
    
    print("Ramping up from 6% back to 7.5%...")
    ramp_pwm(pwm, 6.0, 7.5)
    
    pwm.stop()
    print(f"Automatic test on GPIO pin {pin} completed.\n")

def manual_test(pin):
    """Manual test: Allow user to input PWM duty cycle values until quitting."""
    print(f"\nStarting manual test on GPIO pin {pin}...")
    GPIO.setup(pin, GPIO.OUT)
    pwm = GPIO.PWM(pin, 50)  # 50Hz PWM signal
    pwm.start(7.5)
    
    while True:
        user_input = input("Enter a PWM duty cycle value (or type 'q' to quit manual test): ")
        if user_input.lower() == 'q':
            break
        try:
            duty = float(user_input)
        except ValueError:
            print("Invalid input. Please enter a number or 'q' to quit.")
            continue
        pwm.ChangeDutyCycle(duty)
        print(f"Set duty cycle to {duty}%")
    
    pwm.stop()
    print(f"Manual test on GPIO pin {pin} completed.\n")

def main():
    GPIO.setmode(GPIO.BCM)
    try:
        while True:
            pin_input = input("Enter the GPIO pin to test (or type 'q' to quit): ")
            if pin_input.lower() == 'q':
                break
            try:
                pin = int(pin_input)
            except ValueError:
                print("Invalid GPIO pin number. Please enter an integer.")
                continue

            mode = input("Select test mode - automatic (a) or manual (m): ").lower()
            if mode == 'a':
                automatic_test(pin)
            elif mode == 'm':
                manual_test(pin)
            else:
                print("Invalid selection. Please choose 'a' for automatic or 'm' for manual.")
    finally:
        GPIO.cleanup()
        print("GPIO cleaned up. Exiting program.")

if __name__ == '__main__':
    main()
