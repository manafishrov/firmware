"""Load trusted SDK declarations without invoking actions or background tasks."""

from pathlib import Path
import sys
from types import ModuleType
from typing import ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from .declarations import Script
from .models import Manifest


MAX_SOURCE_BYTES = 262144


class LoadedScript(BaseModel):
    """Own a module for exactly as long as its declarations or tasks need it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    module: ModuleType
    script: Script
    definition: Manifest

    def close(self) -> None:
        """Release this module without disturbing any other loaded revision."""
        if sys.modules.get(self.module.__name__) is self.module:
            del sys.modules[self.module.__name__]


def load_script(source: str, path: Path | None = None) -> LoadedScript:
    """Execute module declarations; hardware access belongs inside async functions."""
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        msg = "Custom action source exceeds 256 KiB"
        raise ValueError(msg)
    filename = str(path) if path is not None else "<custom action>"
    code = compile(source, filename, "exec")
    module = ModuleType(f"manafish_script_{uuid4().hex}")
    module.__file__ = filename
    sys.modules[module.__name__] = module
    try:
        exec(code, module.__dict__)  # noqa: S102 - explicitly trusted Python scripts
        scripts = {
            id(value): value
            for value in vars(module).values()
            if isinstance(value, Script)
        }
        if len(scripts) != 1:
            msg = "Define exactly one Script from manafish_sdk at module level"
            raise ValueError(msg)
        script = next(iter(scripts.values()))
        return LoadedScript(module=module, script=script, definition=script._seal())
    except (SystemExit, KeyboardInterrupt) as error:
        if sys.modules.get(module.__name__) is module:
            del sys.modules[module.__name__]
        msg = f"Custom action import exited: {error}"
        raise RuntimeError(msg) from error
    except BaseException:
        if sys.modules.get(module.__name__) is module:
            del sys.modules[module.__name__]
        raise
