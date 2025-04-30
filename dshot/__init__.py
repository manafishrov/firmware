from .dshot import motorImplementationInitialize, motorImplementationFinalize, motorImplementationSendThrottles, motorImplementationSet3dModeAndSpinDirection

class DShot:
    def __init__(self, pins):
        if not pins or not all(isinstance(p, int) and 0 <= p <= 27 for p in pins):
            raise ValueError("Invalid GPIO pin numbers. Must be integers between 0-27.")

        self.pins = pins
        self.num_pins = len(pins)
        try:
            motorImplementationInitialize(self.pins, self.num_pins)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize DShot: {e}")

    def __del__(self):
        self.finalize()

    def finalize(self):
        motorImplementationFinalize(self.pins, self.num_pins)

    def send_throttles(self, throttles):
        if len(throttles) != self.num_pins:
            raise ValueError("Number of throttle values must match number of pins")
        if not all(isinstance(t, (int, float)) and -1.0 <= t <= 1.0 for t in throttles):
            raise ValueError("Throttle values must be between -1.0 and 1.0")
        try:
            motorImplementationSendThrottles(self.pins, self.num_pins, throttles)
        except Exception as e:
            raise RuntimeError(f"Failed to send throttle values: {e}")

    def set_3d_mode(self, mode3d=False, reverse_direction=False):
        try:
            motorImplementationSet3dModeAndSpinDirection(
                self.pins, 
                self.num_pins, 
                int(mode3d), 
                int(reverse_direction)
            )
        except Exception as e:
            raise RuntimeError(f"Failed to set 3D mode: {e}")
