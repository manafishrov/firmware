{ pkgs, config, nixos-hardware, ... }:
{
  # Nix settings
  system.stateVersion = "24.11";
  nix = {
    optimise.automatic = true;
    settings = {
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
    extraGroups = [ "wheel" "i2c" "video" "networkmanager" ];
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

  # Enable specific hardware support for camera and i2c
  boot = {
    kernelModules = [ "bcm2835-v412" "i2c-bcm2835" ];
    kernelParams = [ "cma=256M" ];
  };
  imports = [
    "${nixos-hardware}/raspberry-pi/4/pkgs-overlays.nix"
  ];
  hardware = {
    i2c.enable = true; # Adds "i2c-dev" kernel module and creates i2c group
    raspberry-pi."4".apply-overlays-dtmerge.enable = true; # This and the overlays import make the device tree overlays work (it is not specific to the 4 even though it is labeled as such)
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
        [
          {
            name = "i2c1";
            dtsFile = mkCompatibleDtsFile "${config.boot.kernelPackages.kernel}/dtbs/overlays/i2c1.dtbo";
          }
          {
            name = "ov5647";
            dtsFile = mkCompatibleDtsFile "${config.boot.kernelPackages.kernel}/dtbs/overlays/ov5647.dtbo";
          }
        ];
    };
  };

  # Setup MediaMTX
  services.mediamtx = {
    enable = true;
    allowVideoAccess = true;
    settings = {
      rtsp = false;
      rtmp = false;
      hls = false;
      srt = false;
      webrtc = true;
      webrtcAddress = ":8889";
      paths = {
        cam = {
          runOnInit = "${pkgs.ffmpeg}/bin/ffmpeg -f v4l2 -i /dev/video0 -c:v libx264 -pix_fmt yuv420p -preset ultrafast -b:v 600k -f rtsp rtsp://localhost:8889/$MTX_PATH";
          runOnInitRestart = true;
        };
      };
    };
  };

  # Packages
  environment.systemPackages = with pkgs; [
    i2c-tools
    v4l-utils
    neovim
    nano
    ffmpeg
    (python3.withPackages (pypkgs: with pypkgs; [
      pip
      numpy
      websockets
      smbus2
    ]))
  ];

  # Adding these packages to the library path is required for installing packages with pip (So people can install their own packages)
  environment.sessionVariables = {
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      pkgs.stdenv.cc.cc.lib
      pkgs.libz
      pkgs.zlib
      pkgs.openssl
      pkgs.python3
    ];
  };

  # Copy firmware files to pi's home directory
  system.activationScripts.copyFirmwareFiles = {
    deps = [ "users" ];
    text = ''
      mkdir -p /home/pi
      cp -r ${./src}/* /home/pi/
      chown -R pi:pi /home/pi
      find /home/pi -type d -exec chmod 700 {} +
      find /home/pi -type f -exec chmod 600 {} +
    '';
  };

  # Firmware service
  systemd.services.cyberfish-firmware = {
    enable = false;
    description = "Cyberfish Firmware";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" "mediamtx.service" ];
    serviceConfig = {
      Type = "simple";
      User = "pi";
      WorkingDirectory = "/home/pi";
      ExecStart = "${pkgs.python3}/bin/python3 main.py";
      Restart = "always";
      RestartSec = "5";
    };
  };
}
