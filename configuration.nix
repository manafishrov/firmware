{ pkgs, ... }:
{
  # Nix settings
  system.stateVersion = "24.11";
  nix.settings = {
    auto-optimise-store = true;
    builders-use-substitutes = true;
    extra-experimental-features = [ "flakes" "nix-command" ];
    substituters = [
      "https://cache.nixos.org"
      "https://nix-community.cachix.org"
    ];
    trusted-public-keys = [
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
    ];
  };

  # Enable legally redistributable firmware (required for Raspberry Pi hardware)
  hardware.enableRedistributableFirmware = true;

  # Login credentials
  users.users.pi = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    password = "cyberfish";
  };

  # Static IP
  networking = {
    hostName = "cyberfish";
    interfaces.eth0 = {
      useDHCP = false;
      ipv4.addresses = [{
        address = "10.10.10.10";
        prefixLength = 24;
      }];
    };
  };

  # Enable Wi-Fi (For downloading temporary packages or files, if permanent should instead be included in this configuration)
  networking.networkmanager.enable = true;

  # Enable SSH
  services.openssh = {
    enable = true;
    settings.PasswordAuthentication = true;
  };

  # Enable camera
  # https://wiki.nixos.org/wiki/NixOS_on_ARM/Raspberry_Pi
  boot = {
    kernelModules = [ "bcm2835-v4l2" ];
    loader.raspberryPi = {
      enable = true;
      version = 3;
      uboot.enable = true;
      firmwareConfig = ''
        start_x=1
        gpu_mem=256
      '';
    };
  };

  # Packages
  environment.systemPackages = with pkgs; [
    neovim
    nano
    python3.withPackages (pypkgs: with pypkgs; [
      numpy
      websockets
      smbus2
      i2c-tools
    ])
  ];

  # Adding these packages to the library path is required for installing packages with pip (Only for temporary use)
  # https://www.youtube.com/watch?v=6fftiTJ2vuQ
  environment.sessionVariables = {
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      pkgs.stdenv.cc.cc.lib
      pkgs.libz
    ];
  };

  # Modules
  imports = [
    ./modules/mediamtx.nix
    ./modules/dshot.nix
  ];
}
