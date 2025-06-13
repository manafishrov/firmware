import numpy as np
from imu import IMU
from thrusters import ThrusterController
import time
from scipy.optimize import curve_fit

# We have a few options here in regards to calibration done before the relay auto-tuning:
# 1. Slowly increase actuation until we are at angle 0, then use that as zero-point for a, then start 
#    by low a amplitude and increase it until we get oscillations of about 30 deg.
# 2. Set whatever we angle the system is naturally at as zero-point, calculate the desired angle applitude
#    based on that

# How the system behaves in roll is dependent on pitch vice versa, how to fix this:
# 1. First find the zero-point of pitch AND roll, then use that as standby 
#    value (this is problemtaic for systems where center of mass=center of buoyancy)
# 2. Just do pitch first then roll, cause roll will probably rest at 0 if ROV is symmetric

def relay_auto_tuning():
    print("Starting RELAY AUTO TUNING")

    imu = IMU()
    thruster_ctrl = ThrusterController(imu)

    time.sleep(1) 

    print("Checking roll value")
    imu.update_pitch_roll()
    roll = imu.current_roll
    #TODO: Remove this and allow for non-symmetric ROVs
    if abs(roll) > 10:
        print(f"Roll is too high to get good tuning: {roll} degrees, please adjust the ROV buoyancy or ballast tanks to make it level") #
        raise RuntimeError(f"ROV roll is {roll}°, out of tolerance for auto-tuning")
    else:
        print(f"Roll is at {roll} degrees, proceeding with tuning")

    print("Slowly changing pitch actuation to find pitch actuation neccessary to reach 0 degrees")
    pitch_zero_found = False
    pitch_actuation = 0.0
    while not pitch_zero_found:
        thruster_ctrl.run_thrusters([0, 0, 0, pitch_actuation, 0, 0]) # [forward, side, up, pitch, yaw, roll]

        imu.update_pitch_roll()
        pitch = imu.current_pitch
        print(f"Current pitch: {pitch} degrees, actuation: {pitch_actuation}")

        if abs(pitch) < 3:
            pitch_zero_found = True
            print(f"Pitch zero found at actuation: {pitch_actuation}")
        else:
            if pitch > 0:
                pitch_actuation += 0.001
            elif pitch < 0:
                pitch_actuation -= 0.001

        time.sleep(0.02) # Frequency of 50 Hz

    print("Finding a (relay amplitude) for pitch oscillation")
    a = 0
    while True:
        imu.update_pitch_roll()
        pitch = imu.current_pitch

        a += 0.002
        print(f"Current a: {a}")

        if pitch > 0:
            thruster_ctrl.run_thrusters([0, 0, 0, pitch_actuation + a, 0, 0]) # [forward, side, up, pitch, yaw, roll]
        else:
            thruster_ctrl.run_thrusters([0, 0, 0, pitch_actuation-a, 0, 0]) # [forward, side, up, pitch, yaw, roll]

        if abs(pitch) > 30:
            print(f"Oscillation of 30 degrees achieved with a = {a}")
            break

    print(f"Starting relay auto-tuning")
    curve_values = np.array([])
    for i in range(500): #10 seconds at 50 Hz
        imu.update_pitch_roll()
        pitch = imu.current_pitch
        current_time = time.time()
        
        if pitch > 0:
            thruster_ctrl.run_thrusters([0, 0, 0, pitch_actuation + a, 0, 0]) # [forward, side, up, pitch, yaw, roll]
        else:
            thruster_ctrl.run_thrusters([0, 0, 0, pitch_actuation-a, 0, 0]) # [forward, side, up, pitch, yaw, roll]

        curve_values = np.append(curve_values, [current_time, pitch])

        time.sleep(0.02)  # Frequency of 50 Hz

    print("Stopping thrusters")
    thruster_ctrl.run_thrusters([0, 0, 0, 0, 0, 0])
    
    print("Relay auto-tuning complete - fitting curve to data")

    def sine_wave(x, A, f, phi, offset):
        return A * np.sin(2* np.pi * f* x + phi) + offset
    
    time_data = curve_values[0::2]
    pitch_data = curve_values[1::2]
    time_data -= time_data[0]  # Normalize time to start at 0
 

    initial_guess = [(np.max(pitch_data) - np.min(pitch_data))/2, 1/10, 0, np.mean(pitch_data)] 
    try:
        params, _ = curve_fit(sine_wave, time_data, pitch_data, p0=initial_guess)
        A, f, phi, offset = params

        T_u = 1 / f
        print(f"Period: {T_u} seconds, Amplitude: {A}")

    except Exception as e:
        print(f"Error during curve fitting: {e}")
        return
    
    print("Doing calculations for auto tuning")
    K_u = (4 * a) / (np.pi*A)

    K_p = 0.6 * K_u
    K_i = 1.2 * K_u / T_u
    K_d = 0.075 * K_u * T_u

    print(f"Calculated PID parameters for pitch: K_p = {K_p}, K_i = {K_i}, K_d = {K_d}")
    print("Waiting 5 seconds for pitch to settle")
    print()
    time.sleep(5) 
    
    





    print("STARTING ROLL TUNING")
    print("Checking roll value")
    imu.update_pitch_roll()
    roll = imu.current_roll
    #TODO: Remove this and allow for non-symmetric ROVs
    if abs(roll) > 10:
        print(f"Roll is too high to get good tuning: {roll} degrees, please adjust the ROV buoyancy or ballast tanks to make it level") #
        raise RuntimeError(f"ROV roll is {roll}°, out of tolerance for auto-tuning")
    else:
        print(f"Roll is at {roll} degrees, proceeding with tuning")


    print("Finding a (relay amplitude) for roll oscillation")
    a = 0
    while True:
        imu.update_pitch_roll()
        roll = imu.current_roll
        pitch = imu.current_pitch

        a += 0.002
        print(f"Current a: {a}")

        if roll > 0:
            thruster_ctrl.run_thrusters([0, 0, 0, -pitch*K_p*0.5, 0, a])
        else:
            thruster_ctrl.run_thrusters([0, 0, 0, -pitch*K_p*0.5, 0, -a]) # [forward, side, up, pitch, yaw, roll]

        if abs(roll) > 30:
            print(f"Oscillation of 30 degrees achieved with a = {a}")
            break

    print(f"Starting relay auto-tuning for roll")
    curve_values = np.array([])
    for i in range(500): #10 seconds at 50 Hz
        imu.update_pitch_roll()
        roll = imu.current_roll
        pitch = imu.current_pitch
        current_time = time.time()
      
        if roll > 0:
            thruster_ctrl.run_thrusters([0, 0, 0, -pitch*K_p*0.5, 0, a]) # [forward, side, up, pitch, yaw, roll]
        else:
            thruster_ctrl.run_thrusters([0, 0, 0, -pitch*K_p*0.5, 0, -a]) # [forward, side, up, pitch, yaw, roll]

        curve_values = np.append(curve_values, [current_time, pitch])

        time.sleep(0.02)  # Frequency of 50 Hz

    print("Stopping thrusters")
    thruster_ctrl.run_thrusters([0, 0, 0, 0, 0, 0])
    
    print("Relay auto-tuning complete - fitting curve to data")

    print("Relay auto-tuning complete - fitting curve to data")

    def sine_wave(x, A, f, phi, offset):
        return A * np.sin(2* np.pi * f* x + phi) + offset
    
    time_data = curve_values[0::2]
    pitch_data = curve_values[1::2]
    time_data -= time_data[0]  # Normalize time to start at 0
 

    initial_guess = [(np.max(pitch_data) - np.min(pitch_data))/2, 1/10, 0, np.mean(pitch_data)] 
    try:
        params, _ = curve_fit(sine_wave, time_data, pitch_data, p0=initial_guess)
        A, f, phi, offset = params

        T_u = 1 / f
        print(f"Period: {T_u} seconds, Amplitude: {A}")

    except Exception as e:
        print(f"Error during curve fitting: {e}")
        return
    
    print("Doing calculations for auto tuning")
    K_u = (4 * a) / (np.pi*A)

    K_p = 0.6 * K_u
    K_i = 1.2 * K_u / T_u
    K_d = 0.075 * K_u * T_u

    print(f"Calculated PID parameters for roll: K_p = {K_p}, K_i = {K_i}, K_d = {K_d}")
    print("Waiting 5 seconds for roll to settle")
    print()
    time.sleep(5) 