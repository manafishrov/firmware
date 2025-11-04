# This script checks that the required packages for the firmware are available.

packages = [
    "pip",
    "numpy",
    "websockets",
    "smbus2",
    "bmi270",
    "ms5837",
    "serial",
]

for pkg in packages:
    try:
        module: object = __import__(pkg)
        version: str = getattr(module, "__version__", "unknown")
    except ImportError:
        pass
