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
    password = "manafish";
    home = "/home/pi";
  };

  # Set the hostname and IP of the Pi
  networking = {
    hostName = "manafish";
    interfaces.eth0.ipv4.addresses = [{
      address = "10.10.10.10";
      prefixLength = 24;
    }];
  };

  # Disable firewall so all ports are open to allow easy configuration
  networking = {
    firewall.enable = false;
    nftables.enable = false;
  };

  # Enable Wi-Fi (For downloading temporary packages or files, if permanent should instead be included in this configuration)
  networking = {
    wireless.iwd.enable = true;
    networkmanager = {
      enable = true;
      wifi.backend = "iwd";
    };
  };

  # mDNS to connect via manafish.local
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    allowInterfaces = [ "eth0" ];
    publish = {
      enable = true;
      addresses = true;
    };
  };

  # Enable SSH
  services.openssh = {
    enable = true;
    settings.PasswordAuthentication = true;
  };

  # Enable V2 Camera by default, UART and I2C with a high baud rate
  hardware = {
    i2c.enable = true;
    raspberry-pi.config.all = {
      dt-overlays = {
        imx219 = {
          enable = true;
          params = {};
        };
      };
      options = {
        enable_uart = {
          enable = true;
          value = true;
        };
      };
      base-dt-params = {
        i2c_arm = {
          enable = true;
          value = "on";
        };
        i2c_arm_baudrate = {
          enable = true;
          value = 1000000;
        };
      };
    };
  };

  # Setup video streaming
  services.go2rtc = {
    enable = true;
    settings = {
      streams.cam = "exec:${pkgs.rpi.rpicam-apps}/bin/libcamera-vid -t 0 -n --inline -o -";
      api = {
        listen = ":1984";
        origin = "*";
      };
      webrtc.listen = ":8555";
      rtsp.listen = "";
      rtmp.listen = "";
    };
  };

  # Packages
  environment.systemPackages = with pkgs; [
    rpi.libcamera
    rpi.rpicam-apps
    i2c-tools
    neovim
    nano
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
      cp -r ${./src}/* /home/pi/
      ln -sf ${./LICENSE} /home/pi/LICENSE
      chown -R pi:pi /home/pi/*
    '';
  };

  # Firmware service
  systemd.services.manafish-firmware = {
    enable = false;
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" "go2rtc.service" ];
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
