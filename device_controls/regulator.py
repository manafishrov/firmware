import numpy as np

pitch = 0
roll = 0

estimated_state = np.array([pitch, roll])
state_integral = 0

# This method is similar to a luenberger observer, but somewhat different because i use 
def update_estimated_state(previous_state, gyro_measure, accel_measure, dt):
    estimate = previous_state + gyro_measure * dt

    estimate_error = accel_measure - estimate

    L = 0.1
    estimate = estimate - L * estimate_error * dt

    return estimate



def PID(state, previous_state, state_integral, desired_state, dt):
    Kp = 0.1
    Ki = 0.1
    Kd = 0.1

    error = desired_state - state
    state_integral += error * dt
    derivative = (state - previous_state) / dt

    return Kp * error + Ki * state_integral + Kd * derivative


def regulate_pitch_yaw(direction_vector):
    #This function should get the user input for pitch and roll, then return the actuation directions with the help of PID
    
    pass







