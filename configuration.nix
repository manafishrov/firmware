{ pkgs, home-manager, cameraModule, ... }:
let
  pico-sdk-with-submodules = pkgs.pico-sdk.override {
    withSubmodules = true;
  };

  streamingResolution =
    if cameraModule == "imx219" then "1640x1232"
    else if cameraModule == "imx477" then "2028x1520"
    else "1280x960";
in
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
    extraGroups = [ "wheel" "networkmanager" "video" "i2c" "dialout" ];
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

  # Enable camera, UART and I2C with a high baud rate
  hardware = {
    i2c.enable = true;
    raspberry-pi.config.all = {
      dt-overlays = {
        ${cameraModule} = {
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
        camera_auto_detect = {
          enable = true;
          value = false;
        };
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
      streams.cam =
        "exec:${pkgs.rpi.rpicam-apps}/bin/libcamera-vid -t 0 -n --inline -o - --framerate 30 "
        + "--width ${builtins.elemAt (builtins.splitString "x" streamingResolution) 0} "
        + "--height ${builtins.elemAt (builtins.splitString "x" streamingResolution) 1}";
      api = {
        listen = ":1984";
        origin = "*";
      };
      webrtc.listen = ":8555";
      rtsp.listen = "";
      rtmp.listen = "";
    };
  };

  # System packages
  environment = {
    systemPackages = with pkgs; [
      rpi.libcamera
      rpi.rpicam-apps
      i2c-tools
      cmake
      gnumake
      gcc-arm-embedded
      picotool
      pico-sdk-with-submodules
      (python3.withPackages (pypkgs: with pypkgs; [
        pip
        numpy
        websockets
        smbus2
      ] ++ [
        (pkgs.python3Packages.buildPythonPackage {
          pname = "bmi270";
          version = "0.4.3";
          src = pkgs.fetchFromGitHub {
            owner = "CoRoLab-Berlin";
            repo = "bmi270_python";
            rev = "main";
            hash = "sha256-IxkMWWcrsglFV5HGDMK0GBx5o0svNfRXqhW8/ZWpsUk=";
          };
          doCheck = false;
        })
        (pkgs.python3Packages.buildPythonPackage {
          pname = "ms5837";
          version = "0.1.0";
          src = pkgs.fetchFromGitHub {
            owner = "bluerobotics";
            repo = "ms5837-python";
            rev = "master";
            hash = "sha256-a6P3zHAw5YPlgiznX2lHJs2EI3xwPOqI49lA/xP+I49lO+m+f9iw=";
          };
          doCheck = false;
        })
      ]))
    ];
    sessionVariables = {
      PICO_SDK_PATH = "${pico-sdk-with-submodules}/lib/pico-sdk";
      LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
        pkgs.stdenv.cc.cc.lib
        pkgs.libz
        pkgs.zlib
        pkgs.openssl
        pkgs.python3
      ];
    };
  };

  # Copy firmware files to pi's home directory and setup user packages
  home-manager = {
    useUserPackages = true;
    useGlobalPkgs = true;
    users.pi = {
      home = {
        stateVersion = "25.05";
        packages = with pkgs; [
          neovim
          nano
        ];
        file.LICENSE.source = ./LICENSE;
        activation.copyFirmwareFiles = home-manager.lib.hm.dag.entryAfter ["writeBoundary"] ''
          cp -r ${./src}/* $tmpdir/
        '';
      };
    };
  };

  # Services
  systemd.services = {
    manafish-firmware = {
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
  };
}
