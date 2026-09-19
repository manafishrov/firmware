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
	"gpiozero"
	"lgpio"
	"psutil"
	"ruff"
)

# Custom packages from flake inputs
CUSTOM_VERSION_PACKAGES=(
	"numpydantic"
	"bmi270"
)

CUSTOM_GIT_PACKAGES=(
	"ms5837:ms5837-src:https://github.com/bluerobotics/ms5837-python.git"
)

echo "  python..."
python_version=$(nix eval --raw --inputs-from . "nixpkgs#python313.version" 2>/dev/null)
if [ -n "$python_version" ]; then
	echo "    $python_version"
	sed -i -E "s/requires-python = \"==3\.[0-9]+(\.[0-9]+|(\.\*))?\"/requires-python = \"==$python_version\"/" pyproject.toml
else
	echo "    WARNING: Could not find Python version in nixpkgs"
fi

for pkg in "${PACKAGES[@]}"; do
	echo "  $pkg..."
	version=$(nix eval --raw --inputs-from . "nixpkgs#python313Packages.${pkg}.version" 2>/dev/null)

	if [ -n "$version" ]; then
		echo "    $version"
		# Match only the version chars so any trailing PEP 508 marker
		# (e.g. `; sys_platform == 'linux' ...`) is preserved.
		sed -i -E "s/\"$pkg==[0-9][0-9a-zA-Z.+-]*/\"$pkg==$version/" pyproject.toml
	else
		echo "    WARNING: Could not find version for $pkg in nixpkgs"
	fi
done

echo "  ty..."
ty_version=$(nix eval --raw --inputs-from . "nixpkgs#ty.version" 2>/dev/null)
if [ -n "$ty_version" ]; then
	ty_pep440=$(echo "$ty_version" | sed -E 's/-alpha\.?/a/; s/-beta\.?/b/; s/-rc\.?/rc/')
	echo "    $ty_version -> $ty_pep440"
	sed -i -E "s/\"ty==[^\"]+\"/\"ty==$ty_pep440\"/" pyproject.toml
else
	echo "    WARNING: Could not find version for ty in nixpkgs"
fi

NIX_PKG_FILE="nix/firmware.nix"

for pkg in "${CUSTOM_VERSION_PACKAGES[@]}"; do
	echo "  $pkg (custom version)..."
	version=$(sed -n "/pname = \"$pkg\";/,/version =/p" "$NIX_PKG_FILE" | grep "version =" | sed -E 's/.*version = "([^"]+)";.*/\1/')

	if [ -n "$version" ]; then
		echo "    $version"
		sed -i -E "s/\"$pkg==[^\"]+\"/\"$pkg==$version\"/" pyproject.toml
	else
		echo "    WARNING: Could not find version for $pkg in $NIX_PKG_FILE"
	fi
done

for entry in "${CUSTOM_GIT_PACKAGES[@]}"; do
	pkg="${entry%%:*}"
	input="${entry#*:}"
	input="${input%%:*}"
	url="${entry#*:}"
	url="${url#*:}"

	echo "  $pkg (custom git)..."
	rev=$(nix flake metadata --json | jq -r ".locks.nodes.\"$input\".locked.rev")

	if [ -n "$rev" ] && [ "$rev" != "null" ]; then
		echo "    $rev"
		sed -i -E "s|\"$pkg @ git\+${url}@[a-f0-9]+\"|\"$pkg @ git\+${url}@$rev\"|" pyproject.toml
	else
		echo "    WARNING: Could not find revision for $input in flake.lock"
	fi
done

# Nix builds numpydantic from this exact flake input, which can advance between
# releases. A PyPI version alone does not reproduce that source. Match both the
# source and the metadata version supplied by nixpkgs' pdm-backend setup hook.
numpydantic_rev=$(jq -er '.nodes["numpydantic-src"].locked.rev | select(test("^[0-9a-f]{40}$"))' flake.lock)
numpydantic_version=$(sed -n '/pname = "numpydantic";/,/version =/p' "$NIX_PKG_FILE" | grep 'version =' | sed -E 's/.*version = "([^"]+)";.*/\1/')
test -n "$numpydantic_version"
begin='# BEGIN generated Nix Python sources'
end='# END generated Nix Python sources'
begin_count=$(grep -c -F -x "$begin" pyproject.toml || true)
end_count=$(grep -c -F -x "$end" pyproject.toml || true)
if [ "$begin_count" != "$end_count" ] || [ "$begin_count" -gt 1 ]; then
	echo "Invalid generated Nix Python sources block in pyproject.toml" >&2
	exit 1
fi
sed -i "/^$begin\$/,/^$end\$/d" pyproject.toml
cat >>pyproject.toml <<EOF
$begin
[tool.uv.sources]
numpydantic = { git = "https://github.com/p2p-ld/numpydantic.git", rev = "$numpydantic_rev" }

[tool.uv.extra-build-variables.numpydantic]
PDM_BUILD_SCM_VERSION = "$numpydantic_version"
$end
EOF

echo "Done! pyproject.toml updated with versions and sources from Nix."
