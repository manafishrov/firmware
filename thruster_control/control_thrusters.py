import socket
import json
import time
import keyboard

def get_control_vector():
    forward = (1 if keyboard.is_pressed('w') else 0) + (-1 if keyboard.is_pressed('s') else 0)
    side    = (1 if keyboard.is_pressed('d') else 0) + (-1 if keyboard.is_pressed('a') else 0)
    up      = (1 if keyboard.is_pressed(' ') else 0) + (-1 if keyboard.is_pressed('shift') else 0)
    pitch   = (1 if keyboard.is_pressed('u') else 0) + (-1 if keyboard.is_pressed('j') else 0)
    yaw     = (1 if keyboard.is_pressed('h') else 0) + (-1 if keyboard.is_pressed('k') else 0)
    roll    = (1 if keyboard.is_pressed('y') else 0) + (-1 if keyboard.is_pressed('i') else 0)
    
    quit_flag = 1 if keyboard.is_pressed('esc') else 0

    return [forward, side, up, pitch, yaw, roll, quit_flag]

# SETUP CONNECTION
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)



print("Starting control loop. Press 'esc' to quit.")
while True:
    control_vector = get_control_vector()
    
    message = json.dumps(control_vector).encode('utf-8')
    
    sock.sendto(message, ("192.168.2.12", 12345))
    
    print(f"Sent: {control_vector}")
    
    if control_vector[6] == 1:
        print("Quit signal received. Exiting.")
        break
  
    time.sleep(0.05)

