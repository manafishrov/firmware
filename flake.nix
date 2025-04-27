{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11?shallow=1";
    nixos-hardware.url = "github:NixOS/nixos-hardware?shallow=1";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }:
  {
    nixosConfigurations = {
      cyberfish = nixpkgs.lib.nixosSystem {
        system = "aarch64-linux";
        modules = [
          nixos-hardware.nixosModules.raspberry-pi-3
          "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
          ./camera
          ./configuration.nix
        ];
      };
    };
    # Build to create SD image
    packages.aarch64-linux.sdImage = self.nixosConfigurations.cyberfish.config.system.build.sdImage;
  };
}
