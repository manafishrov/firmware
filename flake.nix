{
  nixConfig = {
    extra-substituters = [
      "https://cache.nixos.org"
      "https://nix-community.cachix.org"
      "https://nixos-raspberrypi.cachix.org"
    ];
    extra-trusted-public-keys = [
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
      "nixos-raspberrypi.cachix.org-1:4iMO9LXa8BqhU+Rpg6LQKiGa2lsNh/j2oiYLNOQ5sPI="
    ];
  };

  inputs = {
    # Rev-pinned so flake.lock can't drift on local nix commands. Renovate's
    # nix manager bumps this string, gated by minimumReleaseAge in
    # .github/renovate.json so nixos-raspberrypi.cachix.org has time to
    # populate aarch64 substitutes before we move.
    nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi/d567e94380c2911ca9fd623ee1bef35ddd6157d9";
    nixpkgs.follows = "nixos-raspberrypi/nixpkgs";
    impermanence = {
      url = "github:nix-community/impermanence";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    ms5837-src = {
      url = "github:bluerobotics/ms5837-python";
      flake = false;
    };
    numpydantic-src = {
      url = "github:p2p-ld/numpydantic";
      flake = false;
    };
    bmi270-src = {
      url = "github:CoRoLab-Berlin/bmi270_python";
      flake = false;
    };
    mcu-firmware-pico = {
      url = "https://github.com/manafishrov/mcu-firmware/releases/download/v1.0.2/pico-v1.0.2.uf2";
      flake = false;
    };
    mcu-firmware-pico2 = {
      url = "https://github.com/manafishrov/mcu-firmware/releases/download/v1.0.2/pico2-v1.0.2.uf2";
      flake = false;
    };
  };

  outputs = {
    self,
    nixpkgs,
    nixos-raspberrypi,
    impermanence,
    treefmt-nix,
    ...
  } @ inputs: let
    mcuFirmwareVersion = "v1.0.2";
    supportedSystems = [
      "aarch64-linux"
      "x86_64-linux"
      "aarch64-darwin"
    ];

    version = self.shortRev or self.dirtyShortRev or "dev";

    forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
  in {
    nixosConfigurations.pi3-imx477 = nixos-raspberrypi.lib.nixosSystem {
      specialArgs = {
        inherit inputs version nixos-raspberrypi mcuFirmwareVersion;
      };
      modules = [
        nixos-raspberrypi.nixosModules.raspberry-pi-3.base
        nixos-raspberrypi.nixosModules.sd-image
        impermanence.nixosModules.impermanence
        {
          system.stateVersion = "25.11";
          image.fileName = "pi3-imx477-${version}.img";
          documentation = {
            enable = false;
            doc.enable = false;
            info.enable = false;
            man.enable = false;
            nixos.enable = false;
          };
        }
        ./nix/camera.nix
        ./nix/sensors.nix
        ./nix/mcu.nix
        ./nix/networking.nix
        ./nix/firmware.nix
        ./nix/system.nix
        ./nix/impermanence.nix
      ];
    };

    packages = forAllSystems (_: {
      inherit (self.nixosConfigurations.pi3-imx477.config.system.build) sdImage;
      default = self.nixosConfigurations.pi3-imx477.config.system.build.sdImage;
    });

    formatter = forAllSystems (system:
      (treefmt-nix.lib.evalModule nixpkgs.legacyPackages.${system} {
        projectRootFile = "flake.nix";
        programs = {
          alejandra.enable = true;
          statix.enable = true;
          deadnix.enable = true;
        };
      })
      .config
      .build
      .wrapper);

    devShells = forAllSystems (system: let
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      default = pkgs.mkShell {
        buildInputs = [
          pkgs.minisign
          pkgs.uv
          pkgs.python313
        ];
        env = {
          UV_PYTHON_DOWNLOADS = "never";
          UV_PYTHON = nixpkgs.lib.getExe pkgs.python313;
          LD_LIBRARY_PATH = nixpkgs.lib.makeLibraryPath [pkgs.stdenv.cc.cc.lib pkgs.zlib];
        };
        # uv installs ruff and ty (pinned in pyproject.toml) as prebuilt PyPI
        # wheels whose ELF interpreter is /lib64/ld-linux-x86-64.so.2, which
        # NixOS lacks. Patch the venv binaries to the nix loader so `uv run
        # ruff` / `uv run ty` work the same on NixOS as on every other OS — one
        # invocation path everywhere (local, pre-commit, CI). No-op off NixOS.
        shellHook = ''
          if [ -e /etc/NIXOS ] && [ -f pyproject.toml ]; then
            ${pkgs.lib.getExe pkgs.uv} sync --quiet
            _loader="${pkgs.stdenv.cc.libc}/lib/ld-linux-x86-64.so.2"
            for _bin in ruff ty; do
              _path=".venv/bin/$_bin"
              if [ -f "$_path" ] && \
                 [ "$(${pkgs.patchelf}/bin/patchelf --print-interpreter "$_path" 2>/dev/null)" != "$_loader" ]; then
                ${pkgs.patchelf}/bin/patchelf --set-interpreter "$_loader" "$_path" || true
              fi
            done
            unset _loader _bin _path
          fi
        '';
      };
    });
  };
}
