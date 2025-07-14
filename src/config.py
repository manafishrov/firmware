import json
import os
import threading

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
_config_cache = None
_config_lock = threading.Lock()


def get_config():
    global _config_cache
    with _config_lock:
        if _config_cache is None:
            with open(_CONFIG_PATH, "r") as f:
                _config_cache = json.load(f)
        return _config_cache


def set_config(config):
    with _config_lock:
        with open(_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        global _config_cache
        _config_cache = config
