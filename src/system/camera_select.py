import os
import sys
from typing import Dict, Tuple
from pathlib import Path


class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    NC = "\033[0m"


CAMERAS: Dict[int, Tuple[str, str]] = {
    1: ("ov5647", "V1 Camera (5MP)"),
    2: ("imx219", "V2 Camera (8MP)"),
    3: ("imx708", "V3 Camera (12MP)"),
    4: ("imx477", "HQ Camera (12.3MP)"),
    5: ("imx500", "AI Camera"),
    6: ("imx296", "Global Shutter Camera"),
    7: ("imx290", "Sony IMX290"),
    8: ("imx327", "Sony IMX327"),
    9: ("imx378", "Sony IMX378"),
    10: ("imx519", "Sony IMX519"),
    11: ("ov9281", "OmniVision OV9281"),
}

CONFIG_FILE = Path("/boot/config.txt")


def print_colored(text: str, color: str) -> None:
    print(f"{color}{text}{Colors.NC}")


def show_menu() -> None:
    print_colored("Available Cameras:", Colors.GREEN)
    print("------------------------")
    for num, (_, description) in CAMERAS.items():
        print(f"{num}) {description}")
    print("------------------------")


def check_sudo() -> bool:
    return os.geteuid() == 0


def update_config(overlay: str) -> bool:
    try:
        if not CONFIG_FILE.exists():
            print_colored(f"Error: {CONFIG_FILE} not found!", Colors.YELLOW)
            return False

        with open(CONFIG_FILE, "r") as f:
            lines = f.readlines()

        lines = [
            line
            for line in lines
            if not any(
                line.strip().startswith(f"dtoverlay={cam[0]}")
                for cam in CAMERAS.values()
            )
        ]

        lines.append(f"dtoverlay={overlay}\n")

        with open(CONFIG_FILE, "w") as f:
            f.writelines(lines)

        print_colored(f"Successfully updated camera to: {overlay}", Colors.GREEN)
        print("Please reboot your Raspberry Pi for changes to take effect.")
        return True

    except Exception as e:
        print_colored(f"Error updating config: {e}", Colors.YELLOW)
        return False


def main() -> None:
    if not check_sudo():
        print_colored(
            "This script needs to be run with sudo privileges.", Colors.YELLOW
        )
        sys.exit(1)

    print_colored("Raspberry Pi Camera Selection Tool", Colors.GREEN)
    print("This tool will help you switch between different camera modules.")
    print()

    show_menu()
    print()

    try:
        selection = int(input(f"Enter the number of your camera (1-{len(CAMERAS)}): "))
        if selection not in CAMERAS:
            print_colored("Invalid selection. Please try again.", Colors.YELLOW)
            sys.exit(1)

        overlay, _ = CAMERAS[selection]
        update_config(overlay)

    except ValueError:
        print_colored("Please enter a valid number.", Colors.YELLOW)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
