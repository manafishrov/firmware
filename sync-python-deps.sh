#!/usr/bin/env bash
# Sync Python package versions from nixpkgs to pyproject.toml
# Uses the exact pinned nixpkgs version from flake.lock
# Run this after updating nixpkgs to keep pyproject.toml in sync

set -euo pipefail

# Python packages to sync from nixpkgs
# Format: "nixpkgs_name:pyproject_name"
# Core packages from nixpkgs
PACKAGES=(
	"numpy"
	"websockets"
	"pydantic"
	"smbus2"
	"scipy"
	"pyserial-asyncio-fast"
)

# Custom packages from flake inputs
CUSTOM_VERSION_PACKAGES=(
	"numpydantic"
	"bmi270"
)

CUSTOM_GIT_PACKAGES=(
	"ms5837:ms5837-src:https://github.com/bluerobotics/ms5837-python.git"
)

for pkg in "${PACKAGES[@]}"; do
	echo "  $pkg..."
	version=$(nix eval --raw --inputs-from . "nixpkgs#python313Packages.${pkg}.version" 2>/dev/null)

	if [ -n "$version" ]; then
		echo "    $version"
		sed -i -E "s/\"$pkg==[^\"]+\"/\"$pkg==$version\"/" pyproject.toml
	else
		echo "    WARNING: Could not find version for $pkg in nixpkgs"
	fi
done

for pkg in "${CUSTOM_VERSION_PACKAGES[@]}"; do
	echo "  $pkg (custom version)..."
	version=$(sed -n "/pname = \"$pkg\";/,/version =/p" configuration.nix | grep "version =" | sed -E 's/.*version = "([^"]+)";.*/\1/')

	if [ -n "$version" ]; then
		echo "    $version"
		sed -i -E "s/\"$pkg==[^\"]+\"/\"$pkg==$version\"/" pyproject.toml
	else
		echo "    WARNING: Could not find version for $pkg in configuration.nix"
	fi
done

for entry in "${CUSTOM_GIT_PACKAGES[@]}"; do
	pkg="${entry%%:*}"
	input="${entry#*:}"
	input="${input%%:*}"
	url="${entry##*:}"

	echo "  $pkg (custom git)..."
	rev=$(nix flake metadata --json | jq -r ".locks.nodes.\"$input\".locked.rev")

	if [ -n "$rev" ] && [ "$rev" != "null" ]; then
		echo "    $rev"
		sed -i -E "s|\"$pkg @ git\+${url}@[a-f0-9]+\"|\"$pkg @ git\+${url}@$rev\"|" pyproject.toml
	else
		echo "    WARNING: Could not find revision for $input in flake.lock"
	fi
done

echo "Done! pyproject.toml updated with versions from nixpkgs."
