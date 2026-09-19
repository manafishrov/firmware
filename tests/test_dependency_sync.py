"""Verify custom Python sources follow the image lock, not just version labels."""

import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN generated Nix Python sources"


@pytest.fixture
def sync_project(tmp_path: Path) -> Path:
    project = (ROOT / "pyproject.toml").read_text().split(BEGIN, 1)[0]
    (tmp_path / "pyproject.toml").write_text(project)
    (tmp_path / "nix").mkdir()
    (tmp_path / "nix/firmware.nix").write_text((ROOT / "nix/firmware.nix").read_text())
    lock = {
        "nodes": {
            "numpydantic-src": {"locked": {"rev": "a" * 40}},
            "ms5837-src": {"locked": {"rev": "b" * 40}},
        }
    }
    (tmp_path / "flake.lock").write_text(json.dumps(lock))
    (tmp_path / "bin").mkdir()
    nix = tmp_path / "bin/nix"
    nix.write_text(
        "#!/usr/bin/env bash\nset -eu\n"
        "if [ \"$1\" = flake ]; then jq '{locks: .}' flake.lock; "
        'elif [[ "${*: -1}" = *python313.version ]]; then echo 3.13.14; '
        "else echo 1.0; fi\n"
    )
    nix.chmod(0o755)
    return tmp_path


def run_sync(project: Path) -> subprocess.CompletedProcess[str]:
    # Fixed repository script; stub only Nix lookups so tests never fetch/build.
    return subprocess.run(  # noqa: S603
        ["bash", str(ROOT / "sync-python-deps.sh")],  # noqa: S607
        cwd=project,
        env={**os.environ, "PATH": f"{project / 'bin'}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )


def test_sync_preserves_https_and_is_idempotent(sync_project: Path) -> None:
    result = run_sync(sync_project)
    assert result.returncode == 0, result.stderr
    path = sync_project / "pyproject.toml"
    first = path.read_text()
    project = tomllib.loads(first)
    assert (
        f"ms5837 @ git+https://github.com/bluerobotics/ms5837-python.git@{'b' * 40}"
        in project["project"]["dependencies"]
    )
    assert project["tool"]["uv"]["sources"]["numpydantic"]["rev"] == "a" * 40
    assert (
        project["tool"]["uv"]["extra-build-variables"]["numpydantic"][
            "PDM_BUILD_SCM_VERSION"
        ]
        == "1.10.0"
    )
    result = run_sync(sync_project)
    assert result.returncode == 0, result.stderr
    assert path.read_text() == first


def test_sync_advances_source_without_dropping_update(sync_project: Path) -> None:
    assert run_sync(sync_project).returncode == 0
    lock_path = sync_project / "flake.lock"
    lock = json.loads(lock_path.read_text())
    lock["nodes"]["numpydantic-src"]["locked"]["rev"] = "c" * 40
    lock_path.write_text(json.dumps(lock))
    result = run_sync(sync_project)
    assert result.returncode == 0, result.stderr
    project = tomllib.loads((sync_project / "pyproject.toml").read_text())
    assert project["tool"]["uv"]["sources"]["numpydantic"]["rev"] == "c" * 40


def test_sync_rejects_unterminated_generated_block(sync_project: Path) -> None:
    path = sync_project / "pyproject.toml"
    path.write_text(path.read_text() + BEGIN + "\n")
    result = run_sync(sync_project)
    assert result.returncode != 0
    assert "Invalid generated Nix Python sources block" in result.stderr


def test_locked_numpydantic_source_and_metadata_match_nix() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    nix_lock = json.loads((ROOT / "flake.lock").read_text())
    rev = nix_lock["nodes"]["numpydantic-src"]["locked"]["rev"]
    uv = project["tool"]["uv"]
    assert uv["sources"]["numpydantic"]["rev"] == rev
    package = next(p for p in lock["package"] if p["name"] == "numpydantic")
    assert package["source"]["git"].endswith(f"?rev={rev}#{rev}")
    version = re.search(
        r'pname = "numpydantic";\s+version = "([^"]+)";',
        (ROOT / "nix/firmware.nix").read_text(),
    )
    assert version is not None
    assert package["version"] == version[1]
    assert (
        uv["extra-build-variables"]["numpydantic"]["PDM_BUILD_SCM_VERSION"]
        == version[1]
    )
