import numpy as np
import socket
import json


def setup_connection():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('0.0.0.0', 12345))
    print("Socket is set up")
    return s

def get_direction_vector(s):
    #Uses input to make a direction vector containing [forward, side, up, pitch, yaw, roll]
    data, addr = s.recvfrom(1024)
    direction_vector = json.loads(data.decode())
    #Returns first 6 values as one array, last as a single value, the last value is quit value
    return np.array(direction_vector[:6]), direction_vector[6]


