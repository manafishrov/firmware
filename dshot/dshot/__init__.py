from .dshot import motorImplementationInitialize, motorImplementationFinalize, motorImplementationSendThrottles, motorImplementationSet3dModeAndSpinDirection

class DShot:
    def __init__(self, pins):
        self.pins = pins
        self.num_pins = len(pins)
        motorImplementationInitialize(self.pins, self.num_pins)
        
    def __del__(self):
        self.finalize()
        
    def finalize(self):
        motorImplementationFinalize(self.pins, self.num_pins)
        
    def send_throttles(self, throttles):
        if len(throttles) != self.num_pins:
            raise ValueError("Number of throttle values must match number of pins")
        motorImplementationSendThrottles(self.pins, self.num_pins, throttles)
        
    def set_3d_mode(self, mode3d=False, reverse_direction=False):
        motorImplementationSet3dModeAndSpinDirection(self.pins, self.num_pins, int(mode3d), int(reverse_direction))

