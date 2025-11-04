"""This script checks that the required packages for the firmware are available."""

import importlib
import logging
import types


def main() -> None:
    """Check that required packages are available."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

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
            logger.info(f"Package '{pkg}' is available (version: {version})")
        except ImportError:
            logger.error(f"Package '{pkg}' is not available")


if __name__ == "__main__":
    main()
