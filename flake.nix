{
  inputs.nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi?shallow=1";

  outputs = { self, nixos-raspberrypi, ... }:
  {
    nixosConfigurations = {
      cyberfish = nixos-raspberrypi.lib.nixosSystem {
        specialArgs = { inherit nixos-raspberrypi; };
        modules = [
          nixos-raspberrypi.nixosModules.raspberry-pi-02.base
          nixos-raspberrypi.nixosModules.sd-image
          ./configuration.nix
        ];
      };
    };
    packages.default = self.nixosConfigurations.cyberfish.config.system.build.sdImage;
  };
}
