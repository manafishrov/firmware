{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }:
    {
      nixosConfigurations = {
        cyberfish = nixpkgs.lib.nixosSystem {
          system = "aarch64-linux";
          modules = [
            nixos-hardware.nixosModules.raspberry-pi-3
            ./configuration.nix
          ];
        };
      };
      defaultNixosConfiguration = self.nixosConfigurations.cyberfish;
    };
}
