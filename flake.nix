{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11?shallow=1";
    nixos-hardware.url = "github:NixOS/nixos-hardware?shallow=1";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }:
  {
    nixosConfigurations = {
      cyberfish = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit nixos-hardware; };
        system = "aarch64-linux";
        modules = [
          "${nixpkgs}/nixos/modules/installer/sd-card/sd-image-aarch64.nix"
          nixos-hardware.nixosModules.raspberry-pi-3
          ./configuration.nix
        ];
      };
    };
    packages.aarch64-linux.sdImage = self.nixosConfigurations.cyberfish.config.system.build.sdImage;
  };
}
