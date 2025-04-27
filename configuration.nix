{ pkgs, config, ... }:
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

  # Remove documentation to save space
  documentation = {
    enable = false;
    doc.enable = false;
    info.enable = false;
    man.enable = false;
    nixos.enable = false;
  };

  # Login credentials
  users.users.pi = {
    isNormalUser = true;
    extraGroups = [ "wheel" "i2c" ];
    password = "cyberfish";
    home = "/home/pi";
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

  hardware = {
    i2c.enable = true;
    raspberry-pi."4".apply-overlays-dtmerge.enable = true;
    deviceTree = {
      enable = true;
      filter = "bcm2837-rpi-3*";
      overlays =
      let
        mkCompatibleDtsFile = dtbo:
          let
            drv = (pkgs.runCommand (builtins.replaceStrings [ ".dtbo" ] [ ".dts" ] (baseNameOf dtbo)) {
              nativeBuildInputs = with pkgs; [ dtc gnused ];
            }) ''
              mkdir "$out"
              dtc -I dtb -O dts '${dtbo}' | sed -e 's/bcm2835/bcm2837/' > "$out/overlay.dts"
            '';
          in
          "${drv}/overlay.dts";
      in
        [{
          name = "ov5647";
          dtsFile =
            mkCompatibleDtsFile "${config.boot.kernelPackages.kernel}/dtbs/overlays/ov5647.dtbo";
        }];
    };
  };

  # Packages
  environment.systemPackages = with pkgs; [
    neovim
    nano
    i2c-tools
    (python3.withPackages (pypkgs: with pypkgs; [
      numpy
      websockets
      smbus2
    ]))
  ];

  # Adding these packages to the library path is required for installing packages with pip (Only for temporary use)
  # https://www.youtube.com/watch?v=6fftiTJ2vuQ
  # environment.sessionVariables = {
  #   LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
  #     pkgs.stdenv.cc.cc.lib
  #     pkgs.libz
  #   ];
  # };

  # Copy firmware files to pi's home directory
  system.activationScripts.copyFirmwareFiles = {
    deps = ["users"];
    text = ''
      mkdir -p /home/pi
      cp -r ${./src}/* /home/pi/
      chown -R pi:pi /home/pi
    '';
  };

  # Firmware service
  systemd.services.cyberfish-firmware = {
    enable = false;
    description = "Cyberfish Firmware";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" ];
    serviceConfig = {
      Type = "simple";
      User = "pi";
      WorkingDirectory = "/home/pi";
      ExecStart = "${pkgs.python3}/bin/python3 main.py";
      Restart = "always";
      RestartSec = "5";
    };
  };

  # Modules
  imports = [
    ./modules/mediamtx
    ./modules/dshot
  ];
}
