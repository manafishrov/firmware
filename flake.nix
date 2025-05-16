{
  inputs = {
    nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi?shallow=1";
  };

  outputs = { self, nixos-raspberrypi, ... }:
  {
    nixosConfigurations = {
      cyberfish = nixos-raspberrypi.lib.nixosSystem {
        specialArgs = { inherit nixos-raspberrypi; };
        modules = [
          nixos-raspberrypi.nixosModules.raspberry-pi-4.base
          nixos-raspberrypi.nixosModules.sd-image
          ./configuration.nix
        ];
      };
    };
    packages.aarch64-linux.sdImage = self.nixosConfigurations.cyberfish.config.system.build.sdImage;
  };
}
