def test_imports():
    """Test that all required packages are accessible."""
    print("Testing package imports...")

    try:
        import numpy as np
        print("✓ numpy version:", np.__version__)
    except ImportError as e:
        print("✗ numpy import failed:", e)

    try:
        import websockets
        print("✓ websockets version:", websockets.__version__)
    except ImportError as e:
        print("✗ websockets import failed:", e)

    try:
        from smbus2 import SMBus
        print("✓ smbus2 imported successfully")
    except ImportError as e:
        print("✗ smbus2 import failed:", e)

    try:
        from dshot import DShot
        print("✓ dshot package imported successfully")
    except ImportError as e:
        print("✗ dshot import failed:", e)

if __name__ == "__main__":
    print("=== Python Package Availability Test ===")
    test_imports()
    print("=====================================")
