import base64
import gzip
import json
from pathlib import Path

import pytest

from rov_firmware.extensions.source_bundle import (
    SourceBundle,
    _add_file,
    _distributions,
    source_bundle,
)


def test_snapshot_uses_actual_sources_and_dependencies_without_importing_scripts():
    bundle = source_bundle()
    files = json.loads(gzip.decompress(bundle.data))
    root = Path(__file__).parents[1] / "src"
    for name in [
        "manafish_sdk/__init__.py",
        "rov_firmware/rov_state.py",
        "rov_firmware/extensions/sdk.py",
    ]:
        assert files[name] == (root / name).read_text()
    assert "pydantic/main.py" in files
    assert "numpy/__init__.pyi" in files
    assert not any(name.startswith("examples/") for name in files)
    assert source_bundle() is bundle


def test_snapshot_is_chunked_and_rejects_wrong_revision_and_offsets():
    bundle = SourceBundle(revision="abc", data=b"x" * 70000)
    chunk = bundle.read("abc", 0)
    assert isinstance(chunk["data"], str)
    assert len(base64.b64decode(chunk["data"])) == 65536
    assert not chunk["eof"]
    assert bundle.read("abc", 65536)["eof"]
    for offset in [-1, 70001, True, 1.2]:
        with pytest.raises(ValueError):
            bundle.read("abc", offset)
    with pytest.raises(ValueError, match="changed"):
        bundle.read("old", 0)


def test_source_collection_never_executes_python(tmp_path):
    source = tmp_path / "module.py"
    source.write_text('raise RuntimeError("Never execute this")')
    files = {}
    _add_file(files, source, "module.py")
    assert files["module.py"] == source.read_text()
    _add_file(files, source, "../module.py")
    assert list(files) == ["module.py"]


def test_runtime_dependencies_are_found_without_an_installed_firmware_distribution():
    assert any(
        distribution.metadata["Name"] == "pydantic" for distribution in _distributions()
    )
