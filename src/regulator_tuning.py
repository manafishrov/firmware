#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import time
import numpy as np
from thrusters import ThrusterController
from imu import IMU
from regulator import PIDController

# Async wrapper for the blocking input() call
async def ainput(prompt: str) -> str:
    return await asyncio.get_event_loop().run_in_executor(None, input, prompt)

# Async version of your test loop
async def run_test_async(
    thrust_controller: ThrusterController,
    regulator: PIDController,
    imu: IMU,
    desired_pitch: float,
    desired_roll: float
):
    last_called_time = time.time()
    for _ in range(200):
        # compute delta_t
        current_time = time.time()
        delta_t = current_time - last_called_time
        last_called_time = current_time

        # update and compute
        imu.update_pitch_roll()
        direction_vector = regulator.regulate_to_absolute(
            [0, 0, 0, 0, 0, 0],
            desired_pitch,
            desired_roll,
            delta_t
        )
        thrust_vector = thrust_controller.thrust_allocation(direction_vector)
        thrust_vector = thrust_controller.correct_spin_direction(thrust_vector)
        thrust_vector = thrust_controller.adjust_magnitude(thrust_vector, 0.3)
        thrust_vector = np.clip(thrust_vector, -1, 1)

        thrust_controller.send_thrust_vector(thrust_vector)

        # 20 Hz
        await asyncio.sleep(0.05)
    for i in range(10):
        # Stop thrusters
        thrust_controller.send_thrust_vector([0] * 8)
        await asyncio.sleep(0.1)

async def main():
    # Initialization
    imu = IMU()
    thrust_controller = ThrusterController(imu)
    regulator = PIDController(imu)

    await asyncio.sleep(0.1)
    print("Initializing thrusters")
    for _ in range(8):
        thrust_controller.send_thrust_vector([0] * 8)
        await asyncio.sleep(0.1)
    await asyncio.sleep(3)

    # Interactive PID tuning loop
    while True:
        cont = (await ainput("Do you want to test new PID parameters? (y/n): ")).strip().lower()
        if cont == "n":
            print("Exiting.")
            break

        # Read gains
        Kp_pitch = float(await ainput("Enter K_p_pitch value: "))
        Ki_pitch = float(await ainput("Enter K_i_pitch value: "))
        Kd_pitch = float(await ainput("Enter K_d_pitch value: "))

        Kp_roll = float(await ainput("Enter K_p_roll value: "))
        Ki_roll = float(await ainput("Enter K_i_roll value: "))
        Kd_roll = float(await ainput("Enter K_d_roll value: "))

        # Apply them
        regulator.set_Kp_pitch(Kp_pitch)
        regulator.set_Ki_pitch(Ki_pitch)
        regulator.set_Kd_pitch(Kd_pitch)
        regulator.set_Kp_roll(Kp_roll)
        regulator.set_Ki_roll(Ki_roll)
        regulator.set_Kd_roll(Kd_roll)

        # Reset integrators
        regulator.integral_value_pitch = 0
        regulator.integral_value_roll = 0

        # Targets
        pitchVal = float(await ainput("Enter pitch value: "))
        rollVal = float(await ainput("Enter roll value: "))

        print("Regulating to specified values for 10 seconds...")
        await run_test_async(thrust_controller, regulator, imu, pitchVal, rollVal)

if __name__ == "__main__":
    asyncio.run(main())
