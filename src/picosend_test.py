# test_send_uart.py
import picosend_uart

# must match PWM_PINS on the Pico
PIN_LIST = [0, 2, 6, 8, 10, 12, 14, 16]

print('Send a float to one PWM pin; others stay at 0.0.')

while True:
    try:
        pin = int(input(f"Choose pin {PIN_LIST}: "))
        val = float(input("Value: "))
        if pin not in PIN_LIST or not -1.0 <= val <= 1.0:
            print("Invalid pin or value; try again.")
            continue
        arr = [0.0]*8
        arr[PIN_LIST.index(pin)] = val
        picosend_uart.send_thrust(arr)
        print(f"Sent ? GP{pin} = {val:.3f}")
    except KeyboardInterrupt:
        print("\nExiting.")
        break
    except Exception as e:
        print("Error:", e)
