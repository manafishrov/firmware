"""Keep dependency-only PRs from silently skipping their validation jobs."""

import fnmatch
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
CI = (ROOT / ".github/workflows/ci.yaml").read_text()


def filter_patterns(name: str) -> list[str]:
    block = re.search(rf"^            {name}:\n((?:              - .*\n)+)", CI, re.M)
    assert block is not None
    return re.findall(r"- '([^']+)'", block[1])


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yaml",
        ".github/workflows/sync-python-deps.yaml",
        ".github/workflows/build.yaml",
        ".github/workflows/re-upload.yaml",
        ".github/actions/build-and-upload/action.yml",
    ],
)
@pytest.mark.parametrize("job_filter", ["nix", "python", "workflows"])
def test_workflow_changes_run_validation(path: str, job_filter: str) -> None:
    assert any(
        fnmatch.fnmatchcase(path, pattern) for pattern in filter_patterns(job_filter)
    )


@pytest.mark.parametrize(
    "path",
    ["uv.lock", "flake.lock", "flake.nix", "nix/firmware.nix", "sync-python-deps.sh"],
)
def test_runtime_dependency_changes_run_python(path: str) -> None:
    assert any(
        fnmatch.fnmatchcase(path, pattern) for pattern in filter_patterns("python")
    )


def test_smoke_checks_the_actual_release_and_sync_nix_pins() -> None:
    smoke = CI.split("  workflow-smoke:\n", 1)[1].split("  ci:\n", 1)[0]
    for name in ["nix-installer-action", "magic-nix-cache-action"]:
        pattern = rf"DeterminateSystems/{name}@([a-f0-9]{{40}})"
        smoke_pins = re.findall(pattern, smoke)
        assert len(smoke_pins) == 1
        for path in [
            ".github/actions/build-and-upload/action.yml",
            ".github/workflows/sync-python-deps.yaml",
        ]:
            pins = re.findall(pattern, (ROOT / path).read_text())
            assert pins and set(pins) == set(smoke_pins)


def test_smoke_cannot_publish_and_is_required_by_aggregator() -> None:
    smoke = CI.split("  workflow-smoke:\n", 1)[1].split("  ci:\n", 1)[0]
    assert "contents: read" in CI
    assert "secrets." not in smoke
    assert "build-and-upload" not in smoke
    assert "git push" not in smoke
    assert "persist-credentials: false" in smoke
    assert "git diff --exit-code -- pyproject.toml uv.lock" in smoke
    aggregator = CI.split("  ci:\n", 1)[1]
    assert "      - workflow-smoke\n" in aggregator
    assert "WORKFLOW_RESULT: ${{ needs.workflow-smoke.result }}" in aggregator
    assert '"$WORKFLOW_RESULT"' in aggregator
