import json
import os


class ROVState:
    def __init__(self):
        self.config_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(self.config_path, "r") as f:
            self.rov_config = json.load(f)

        self.imu = {"acceleration": 0, "gyroscope": 0, "temperature": 0}
        self.pressure = {"pressure": 0, "temperature": 0, "depth": 0}

    def set_config(self, config):
        self.rov_config = config
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)
