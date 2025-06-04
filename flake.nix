{
  nixConfig = {
    extra-substituters = [
      "https://nixos-raspberrypi.cachix.org"
      "https://nix-community.cachix.org"
    ];
    extra-trusted-public-keys = [
      "nixos-raspberrypi.cachix.org-1:4iMO9LXa8BqhU+Rpg6LQKiGa2lsNOQ5sPI="
      "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
    ];
  };

  inputs = {
    nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi?shallow=1";
    home-manager = {
      url = "github:nix-community/home-manager/release-25.05?shallow=1";
      inputs.nixpkgs.follows = "nixos-raspberrypi/nixpkgs";
    };
  };

  outputs = { self, nixos-raspberrypi, home-manager, ... }:
  let
    cameras = [
      "ov5647"
      "imx219"
      "imx477"
    ];

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

    mkCamera = camera: {
      specialArgs = { 
        inherit nixos-raspberrypi;
        inherit home-manager;
        cameraModule = camera;
      };
      modules = [
        nixos-raspberrypi.nixosModules.sd-image
        home-manager.nixosModules.default
        ./configuration.nix
      ];
    };

    mkConfigurations = let
      mkConfig = pi: camera: {
        name = "manafish-${pi.name}-${camera}";
        value = nixos-raspberrypi.lib.nixosSystem (mkCamera camera // {
          modules = [ pi.module ] ++ (mkCamera camera).modules;
        });
      };
    in
      builtins.listToAttrs (builtins.concatMap 
        (pi: map (camera: mkConfig pi camera) cameras) 
        piVersions
      );

    mkPackages = system: let
      mkPackage = pi: camera: {
        name = "${pi.name}-${camera}";
        value = self.nixosConfigurations."manafish-${pi.name}-${camera}".config.system.build.sdImage;
      };
    in
      builtins.listToAttrs (builtins.concatMap 
        (pi: map (camera: mkPackage pi camera) cameras) 
        piVersions
      );
  in
  {
    nixosConfigurations = mkConfigurations;

    packages = builtins.listToAttrs (map 
      (system: {
        name = system;
        value = mkPackages system;
      })
      supportedSystems
    );
  };
}
