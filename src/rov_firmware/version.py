"""Strict release-version parsing shared by firmware update paths."""

from __future__ import annotations

import re


_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_CANONICAL_RC_RE = re.compile(r"^rc\.[1-9]\d*$")
SemverKey = tuple[int, int, int, int, tuple[tuple[int, int, str], ...]]


def match_semver(version: object) -> re.Match[str] | None:
    """Return a match only for strict SemVer and canonical ``rc.N`` versions."""
    if not isinstance(version, str):
        return None
    match = _SEMVER_RE.fullmatch(version)
    if match is None:
        return None
    prerelease = match.group("prerelease")
    if (
        prerelease is not None
        and prerelease.lower().startswith("rc")
        and _CANONICAL_RC_RE.fullmatch(prerelease) is None
    ):
        return None
    return match


def is_valid_semver(version: object) -> bool:
    """Return whether a value is strict SemVer with canonical RC spelling."""
    return match_semver(version) is not None


def semver_sort_key(version: object) -> SemverKey:
    """Return a SemVer-compatible ordering key, with invalid values first."""
    match = match_semver(version)
    if match is None:
        return (-1, -1, -1, -1, ())

    prerelease = match.group("prerelease")
    prerelease_key: tuple[tuple[int, int, str], ...] = ()
    if prerelease is not None:
        prerelease_key = tuple(
            (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier)
            for identifier in prerelease.split(".")
        )
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if prerelease is None else 0,
        prerelease_key,
    )


def compare_semver(left: object, right: object) -> int:
    """Compare two release versions, returning -1, 0, or 1."""
    left_key = semver_sort_key(left)
    right_key = semver_sort_key(right)
    return (left_key > right_key) - (left_key < right_key)
