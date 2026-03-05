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
    nixpkgs.follows = "nixos-raspberrypi/nixpkgs";
    nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi";
    home-manager = {
      url = "github:nix-community/home-manager/release-25.11";
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
  };

  outputs = {
    self,
    nixpkgs,
    nixos-raspberrypi,
    home-manager,
    ...
  } @ inputs: let
    piVersions = [
      {
        name = "pi3";
        module = nixos-raspberrypi.nixosModules.raspberry-pi-3.base;
      }
      {
        name = "pi4";
        module = nixos-raspberrypi.nixosModules.raspberry-pi-4.base;
      }
    ];

    supportedSystems = [
      "aarch64-linux"
      "x86_64-linux"
      "aarch64-darwin"
    ];

    mkBase = {
      specialArgs = {
        inherit inputs;
        inherit nixos-raspberrypi;
        inherit home-manager;
      };
      modules = [
        nixos-raspberrypi.nixosModules.sd-image
        home-manager.nixosModules.default
        ./configuration.nix
      ];
    };

    mkConfigurations = let
      mkConfig = pi: {
        name = "manafish-${pi.name}";
        value = nixos-raspberrypi.lib.nixosSystem (mkBase
          // {
            modules = [pi.module] ++ mkBase.modules;
          });
      };
    in
      builtins.listToAttrs (map mkConfig piVersions);

    mkPackages = _: let
      mkPackage = pi: {
        name = pi.name;
        value = self.nixosConfigurations."manafish-${pi.name}".config.system.build.sdImage;
      };
    in
      builtins.listToAttrs (map mkPackage piVersions);

    mkFormatter = system: nixpkgs.legacyPackages.${system}.alejandra;
  in {
    nixosConfigurations = mkConfigurations;

    formatter = builtins.listToAttrs (
      map
      (system: {
        name = system;
        value = mkFormatter system;
      })
      supportedSystems
    );

    packages = builtins.listToAttrs (
      map
      (system: {
        name = system;
        value = mkPackages system;
      })
      supportedSystems
    );

    devShells = builtins.listToAttrs (
      map
      (system: let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        name = system;
        value = {
          default = pkgs.mkShell {
            buildInputs = [pkgs.uv];
          };
        };
      })
      supportedSystems
    );
  };
}
