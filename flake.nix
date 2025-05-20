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

  outputs = { nixos-raspberrypi, ... }:
  {
    nixosConfigurations = {
      cyberfish = nixos-raspberrypi.lib.nixosSystem {
        specialArgs = { inherit nixos-raspberrypi; };
        modules = [
          nixos-raspberrypi.nixosModules.raspberry-pi-3.base
        ];
      };
    };
    packages = {
      aarch64-linux.default = nixos-raspberrypi.nixosConfigurations.rpi3-installer.config.system.build.sdImage;
      x86_64-linux.default = nixos-raspberrypi.nixosConfigurations.rpi3-installer.config.system.build.sdImage;
      aarch64-darwin.default = nixos-raspberrypi.nixosConfigurations.rpi3-installer.config.system.build.sdImage;
    };
  };
}
