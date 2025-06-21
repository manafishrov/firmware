import numpy as np
import asyncio
import regulator
import PCA9685_fast as PCA9685
import time

class ThrusterController:
    def __init__(self, imu, PID_enabled = False, regulator_controller=None, bus_num=1, address=0x40, freq=50):
        # Use your PIDController instance (or make one if none provided)
        if regulator_controller is None:
            self.regulator = regulator.PIDController(imu)
        else:
            self.regulator = regulator_controller

        self.PID_enabled = PID_enabled

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

    def adjust_magnitude(self, thrust_vector, magnitude):
        return thrust_vector * magnitude

    def correct_spin_direction(self, thrust_vector):
        spin_directions = np.array([-1, 1, -1, 1, -1, 1, 1, -1])
        return thrust_vector * spin_directions

    def print_thrust_vector(self, thrust_vector):
        print(f"Thrust vector: {thrust_vector}")

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

            print(f"Thrust vectors sent per second: {1 / self.time_delay:.2f}")
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

    def run_thrusters(self, direction_vector):
        # direction_vector: [forward, side, up, pitch, yaw, roll]
        direction_vector = self.tuning_correction(direction_vector)

        if self.PID_enabled:
            direction_vector = self.regulator.regulate_pitch_roll(direction_vector)

        thrust_vector = self.thrust_allocation(direction_vector)
        thrust_vector = self.correct_spin_direction(thrust_vector)
        thrust_vector = self.adjust_magnitude(thrust_vector, 0.3)
        thrust_vector = np.clip(thrust_vector, -1, 1)

        self.send_thrust_vector(thrust_vector)


    def get_desired_pitch_roll(self):
        return self.regulator.desired_pitch, self.regulator.desired_roll
