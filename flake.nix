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
      cyberfish = nixos-raspberrypi.lib.nixosSystemFull {
        specialArgs = { inherit nixos-raspberrypi; };
        modules = [
          nixos-raspberrypi.nixosModules.raspberry-pi-02.base
          nixos-raspberrypi.nixosModules.sd-image
          ./configuration.nix
        ];
      };
    };
    packages = {
      aarch64-linux.default = self.nixosConfigurations.cyberfish.config.system.build.sdImage;
      x86_64-linux.default = self.packages.aarch64-linux.default;
      aarch64-darwin.default = self.packages.aarch64-linux.default;
    };
  };
}
