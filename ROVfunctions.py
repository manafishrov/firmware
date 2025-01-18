import numpy as np
import pygame
import socket 

# INPUT
def get_joystick_input(joystick, config="default"):
    if config == "default":
        forward = joystick.get_axis(2)
        side = joystick.get_axis(3)  
        up = 1 if joystick.get_button(4) else 0
        pitch = joystick.get_axis(0)
        yaw = joystick.get_axis(1)
        roll = 1 if joystick.get_button(5) else 0

        return np.array([forward, side, up, pitch, yaw, roll])
 
def get_keyboard_input():
    keys = pygame.key.get_pressed()
    q = keys[pygame.K_q]
    w = keys[pygame.K_w]
    e = keys[pygame.K_e]
    a = keys[pygame.K_a]
    s = keys[pygame.K_s]
    d = keys[pygame.K_d]
    shift = keys[pygame.K_LSHIFT]
    space = keys[pygame.K_SPACE]
    i = keys[pygame.K_i]
    j = keys[pygame.K_j]
    k = keys[pygame.K_k]
    l = keys[pygame.K_l]

    forward = 0
    if i:
        forward +=1
    if k:
        forward += -1

    side = 0
    if l:
        side+= -1
    if j:
        side += 1

    up = 0
    if space:
        up += 1
    if shift:
        up += -1

    pitch = 0
    if w:
        pitch += -1
    if s:
        pitch += 1

    yaw = 0
    if d:
        yaw += 1
    if a:
        yaw += -1

    roll = 0
    if e:
        roll += 1
    if q:
        roll += -1

    return np.array([forward, side, up, pitch, yaw, roll])

def get_gyro_input():
    return np.array([0, 0, 0, 0, 0, 0])

# THRUST ALLOCATION
def get_thrust_vector(input_vector, thrustAllocationMatrix, input_scaling=1):
    thrust_vector = thrustAllocationMatrix @ input_vector

    # Correct for weaker reverse thrust

    # Normalize thrust vector by dividing by the maximum value
    max_thrust = np.max(np.abs(thrust_vector))
    if max_thrust > 0.001:
        thrust_vector /= max_thrust
    
    thrust_vector *= input_scaling

    return thrust_vector

def get_thrust_allocation_matrix():

    # Thruster positions in [x, y, z, pitch, yaw] format
    thrusterPositionMatrix = np.array([[80, 125, -5, (1/3)*np.pi, (1/2)*np.pi], # Right front
                                    [80, -125, -5, (1/3)*np.pi, -(1/2)*np.pi], # Left front
                                    [0, 120, 30, 0, 0], # Right mid
                                    [0, -120, 30, 0, 0], # Left mid
                                    [-80, 125, -5, (1/3)*np.pi, -(1/2)*np.pi], # Right rear
                                    [-80, -125, -5, (1/3)*np.pi, (1/2)*np.pi]]) # Left rear

    centerOfDrag = np.array([0, 0, 0])

    # Creates a new matrix where the positions are relative to the center of drag
    for i in range(thrusterPositionMatrix.shape[0]):
        thrusterPositionMatrix[i, 0] -= centerOfDrag[0]
        thrusterPositionMatrix[i, 1] -= centerOfDrag[1]
        thrusterPositionMatrix[i, 2] -= centerOfDrag[2]

    # Creates force actuation matrix with trigenometry
    pitch = thrusterPositionMatrix[:, 3]
    yaw = thrusterPositionMatrix[:, 4]
    forceActuationMatrix = np.column_stack((np.cos(pitch) * np.cos(yaw), 
                                            np.cos(pitch) * np.sin(yaw), 
                                            np.sin(pitch)))

    # Creates moment actuation matrix using moment arm
    momentActuationMatrix = np.zeros((6, 3))
    for i in range(thrusterPositionMatrix.shape[0]):
        x = thrusterPositionMatrix[i, 0]
        y = thrusterPositionMatrix[i, 1]
        z = thrusterPositionMatrix[i, 2]
        F_x = forceActuationMatrix[i, 0]
        F_y = forceActuationMatrix[i, 1]
        F_z = forceActuationMatrix[i, 2]
        momentActuationMatrix[i] = [-z*F_x + x*F_z, 
                                    -y*F_x - x*F_y, 
                                    -y*F_z]

    # Combines force and moment actuation matrices into a 6x6 matrix
    actuationMatrix = np.column_stack((forceActuationMatrix, momentActuationMatrix))

    # Thrust allocation matrix is the inverse of the transposed actuation matrix, f = A^T*u
    thrustAllocationMatrix = np.linalg.pinv(actuationMatrix.T)

    return thrustAllocationMatrix


# NETWORK
def setup_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return s

def send_thrust_vector(thrust_vector: np.array, s: socket.socket, ip="123.456.789.0", port=12345):
    s.sendto(thrust_vector.tobytes(), (ip, port))



