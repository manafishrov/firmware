"""ROV Hardware Tools & Diagnostics."""

import asyncio
import logging
import sys

from . import (
    mock_websocket_server,
    test_imu,
    test_packages_available,
    test_pressure_sensor,
    test_thrusters,
)


logging.basicConfig(level=logging.INFO)


def cli() -> None:
    """Interactive CLI menu for ROV tools."""
    _ = sys.stdout.write("\n--- ROV Diagnostic Tools ---\n")
    _ = sys.stdout.write("1. Test IMU\n")
    _ = sys.stdout.write("2. Test Pressure Sensor\n")
    _ = sys.stdout.write("3. Test Thrusters\n")
    _ = sys.stdout.write("4. Check Required Packages\n")
    _ = sys.stdout.write("5. Run Mock Websocket Server\n")
    _ = sys.stdout.write("q. Quit\n")

    choice = input("\nSelect a tool > ").strip().lower()

    if choice in ["q", "quit"]:
        sys.exit(0)

    try:
        if choice == "1":
            test_imu.main()
        elif choice == "2":
            test_pressure_sensor.main()
        elif choice == "3":
            asyncio.run(test_thrusters.main())
        elif choice == "4":
            test_packages_available.main()
        elif choice == "5":
            asyncio.run(mock_websocket_server.main())
        else:
            _ = sys.stdout.write(f"Invalid selection: {choice}")
            sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)
