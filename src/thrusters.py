import numpy as np
import asyncio
import regulator
import regulator_depth_hold
import PCA9685_fast as PCA9685
import time
import config

class ThrusterController:
    def __init__(self, imu, pressure_sensor, regulator_controller=None, bus_num=1, address=0x40, freq=50):
        # Use your PIDController instance (or make one if none provided)
        if regulator_controller is None:
            self.regulator = regulator.PIDController(imu)
        else:
            self.regulator = regulator_controller

        # Initialize depth hold controller
        self.depth_regulator = regulator_depth_hold.DepthHoldController(pressure_sensor, imu)

        self.PID_enabled = False
        self.depth_hold_enabled = False

        self.ptc = config.get_pitch_turn_coefficient()
        self.ytc = config.get_yaw_turn_coefficient()
        self.rtc = config.get_roll_turn_coefficient()

        # State
        self.prev_thrust_vector = None
        self._sending = False

        self.last_send_time = time.time()
        self.time_delay = 0.1

        # PWM DRIVER SETUP
        print(f"Resetting all PCA9685 devices on bus {bus_num}")
        PCA9685.software_reset(bus_num=bus_num)

        print(f"Initializing PCA9685 on bus {bus_num} and setting frequency to {freq} Hz")
        self.pwm = PCA9685.PCA9685(bus_num=bus_num, address=address)
        self.pwm.set_pwm_freq(freq)

        # Prepare allocation matrix
        self.thrust_allocation_matrix = self.get_thrust_allocation_matrix()

    def tuning_correction(self, direction_vector):
        correction_matrix = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0],
            [0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 1]
        ])
        return direction_vector @ correction_matrix

    def get_thrust_allocation_matrix(self):
        # Columns: [forward, side, up, pitch, yaw, roll]
        return np.array([
            [ 1,  1, 0,  0,  0.6,  0],
            [ 1, -1, 0,  0, -0.6,  0],
            [ 0,  0, 1,  1,   0,    1],
            [ 0,  0, 1,  1,   0,   -1],
            [ 0,  0, 1, -1,   0,    1],
            [ 0,  0, 1, -1,   0,   -1],
            [-1,  1, 0,  0, -0.6,  0],
            [-1, -1, 0,  0,  0.6,  0],
        ])

    def thrust_allocation(self, input_vector):
        thrust_vector = self.thrust_allocation_matrix @ input_vector
        return thrust_vector.astype(np.float64)

    def correct_spin_direction(self, thrust_vector):
        spin_directions = np.array([-1, 1, -1, 1, -1, 1, -1, 1])
        return thrust_vector * spin_directions

    def print_thrust_vector(self, thrust_vector):
        print(f"Thrust vector: {thrust_vector}")

    def change_cooridinate_system(self, direction_vector, pitch, roll):
        pitch_g, yaw_g, roll_g = direction_vector[3], direction_vector[4], direction_vector[5]

        # Convert from [forward, side, up, pitch, yaw, roll] to [forward, side, up, pitch, yaw, roll]
        cp, sp = np.cos(np.deg2rad(pitch)), np.sin(np.deg2rad(pitch))
        cr, sr = np.cos(np.deg2rad(roll)), np.sin(np.deg2rad(roll))

        try:
            pitch_l =  cr*pitch_g  + sr*cp*yaw_g * (self.ytc/self.ptc)  # Here we scale so pitch matches yaw
            roll_l  =  roll_g      - sp*yaw_g    * (self.ytc/self.rtc)  # Here we scale so roll matches yaw
            yaw_l   =  cr*cp*yaw_g - sr*pitch_g  * (self.ptc/self.ytc)  # Here we scale so yaw matches pitch
        except ZeroDivisionError:
            pitch_l, yaw_l, roll_l = pitch_g, yaw_g, roll_g
            print("Regulator coordinate system change failed because one of the turn coefficients is 0")

        return np.array([direction_vector[0], direction_vector[1], direction_vector[2], pitch_l, yaw_l, roll_l])

    async def _async_send(self, thrust_vector):
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            await loop.run_in_executor(None, self.pwm.set_all_pwm_scaled, thrust_vector)
            self.prev_thrust_vector = thrust_vector.copy()

            current_time = time.time()
            current_time_delay = current_time - self.last_send_time
            self.time_delay = 0.5 * self.time_delay + 0.5 * current_time_delay
            self.last_send_time = current_time

            #print(f"Thrust vectors sent per second: {1 / self.time_delay:.2f}")
        except Exception as e:
            print(f"Error sending thrust vector via PCA9685_fast: {e}")

        finally:
            self._sending = False

    def send_thrust_vector(self, thrust_vector):
        if self._sending:
            return

        reordered = np.array([
            thrust_vector[3],
            thrust_vector[2],
            thrust_vector[1],
            thrust_vector[0],
            thrust_vector[4],
            thrust_vector[7],
            thrust_vector[6],
            thrust_vector[5]
        ])

        if np.array_equal(reordered, self.prev_thrust_vector):
            return

        self._sending = True
        asyncio.create_task(self._async_send(reordered))

        return thrust_vector

    def run_thrusters(self, direction_vector):
        # direction_vector: [forward, side, up, pitch, yaw, roll]
        direction_vector = self.tuning_correction(direction_vector)

        direction_vector *= config.get_user_max_thrust()

        if self.PID_enabled:
            regulator_actuation = self.regulator.regulate_pitch_roll(direction_vector)
            max = np.max(np.abs(regulator_actuation))
            if max > config.get_regulator_max_thrust():
                regulator_actuation = regulator_actuation * config.get_regulator_max_thrust()/max

            direction_vector = direction_vector + regulator_actuation

        if self.depth_hold_enabled:
            depth_actuation = self.depth_regulator.regulate_depth()
            max = np.max(np.abs(depth_actuation))
            if max > config.get_regulator_max_thrust():
                depth_actuation = depth_actuation * config.get_regulator_max_thrust()/max

            direction_vector = direction_vector + regulator_actuation
            
        if self.PID_enabled:
            pitch, roll = self.imu.get_pitch_roll()
            direction_vector = self.change_cooridinate_system(direction_vector, pitch, roll)

        thrust_vector = self.thrust_allocation(direction_vector)
        thrust_vector = self.correct_spin_direction(thrust_vector)
        thrust_vector = np.clip(thrust_vector, -1, 1)

        self.send_thrust_vector(thrust_vector)


    def get_desired_pitch_roll(self):
        return self.regulator.desired_pitch, self.regulator.desired_roll
