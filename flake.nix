{
  nixConfig = {
    extra-substituters = [
      "https://nixos-raspberrypi.cachix.org"
    ];
    extra-trusted-public-keys = [
      "nixos-raspberrypi.cachix.org-1:4iMO9LXa8BqhU+Rpg6LQKiGa2lsNh/j2oiYLNOQ5sPI="
    ];
  };

  inputs.nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi?shallow=1";

  outputs = { self, nixos-raspberrypi, ... }:
  {
    nixosConfigurations = {
      manafish-pi3 = nixos-raspberrypi.lib.nixosSystem {
        specialArgs = { inherit nixos-raspberrypi; };
        modules = [
          nixos-raspberrypi.nixosModules.sd-image
          nixos-raspberrypi.nixosModules.raspberry-pi-3.base
          ./configuration.nix
        ];
      };
      manafish-pi4 = nixos-raspberrypi.lib.nixosSystem {
        specialArgs = { inherit nixos-raspberrypi; };
        modules = [
          nixos-raspberrypi.nixosModules.sd-image
          nixos-raspberrypi.nixosModules.raspberry-pi-4.base
          ./configuration.nix
        ];
      };
    };
    packages = {
      aarch64-linux = {
        pi3 = self.nixosConfigurations.manafish-pi3.config.system.build.sdImage;
        pi4 = self.nixosConfigurations.manafish-pi4.config.system.build.sdImage;
      };
      x86_64-linux = {
        pi3 = self.nixosConfigurations.manafish-pi3.config.system.build.sdImage;
        pi4 = self.nixosConfigurations.manafish-pi4.config.system.build.sdImage;
      };
      aarch64-darwin = {
        pi3 = self.nixosConfigurations.manafish-pi3.config.system.build.sdImage;
        pi4 = self.nixosConfigurations.manafish-pi4.config.system.build.sdImage;
      };
    };
  };
}
