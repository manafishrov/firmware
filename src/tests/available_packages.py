packages = [
    "pip",
    "numpy",
    "websockets",
    "smbus2",
    "bmi270",
    "ms5837",
]

for pkg in packages:
    try:
        __import__(pkg)
        print(f"Package '{pkg}': AVAILABLE")
    except ImportError:
        print(f"Package '{pkg}': MISSING")
