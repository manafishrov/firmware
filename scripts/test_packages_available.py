"""This script checks that the required packages for the firmware are available."""

import importlib
import types


packages = [
    "pip",
    "numpy",
    "websockets",
    "pydantic",
    "numpydantic",
    "smbus2",
    "scipy",
    "pyserial-asyncio",
    "bmi270",
    "ms5837",
]

for pkg in packages:
    try:
        module: types.ModuleType = importlib.import_module(pkg)
        version: str = getattr(module, "__version__", "unknown")
    except ImportError:
        pass
