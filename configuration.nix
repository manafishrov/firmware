{ pkgs, ... }:
{
  # Nix state version
  system.stateVersion = "25.05";

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

  # Enable I2C with a high baud rate
  hardware = {
    i2c.enable = true; # Adds "i2c-dev" kernel module and creates i2c group
    raspberry-pi.config.all.base-dt-params = {
      i2c = {
        enable = true;
        value = "on";
      };
      i2c_baudrate = {
        enable = true;
        value = "1000000";
      };
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
          source = "rpiCamera";
          sourceType = "yes";
          sourceOnDemandStartTimeout = "1s";
          sourceOnDemandCloseAfter = "1s";
          rpiCameraAfSpeed = "fast";
        };
      };
    };
  };

  # Packages
  environment.systemPackages = with pkgs; [
    libcamera
    i2c-tools
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
