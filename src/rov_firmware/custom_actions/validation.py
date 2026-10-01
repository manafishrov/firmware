"""Discover typed script declarations without invoking registered work."""

from .loading import load_script
from .models import Manifest


def validate_source(source: str) -> Manifest:
    """Load declarations, then release the module without starting its work."""
    loaded = load_script(source)
    try:
        return loaded.definition
    finally:
        loaded.close()
