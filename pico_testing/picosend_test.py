from picosend import send_thrust

print("Enter 8 thrust values (-1, 0, or 1), separated by commas.")
print("Example: 0,0,0,1,1,-1,0,0")

while True:
    try:
        raw = input("Thrust values: ")
        values = [int(v.strip()) for v in raw.split(',')]
        if len(values) != 8 or not all(v in (-1, 0, 1) for v in values):
            print("Invalid input! Please enter exactly 8 numbers (only -1, 0, or 1).")
            continue
        send_thrust(values)
        print(f"Sent: {values}")
    except KeyboardInterrupt:
        print("\nExiting.")
        break
    except Exception as e:
        print("Error:", e)