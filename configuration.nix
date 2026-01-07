{ pkgs, home-manager, cameraModule, ... }:
let
  pico-sdk-with-submodules = pkgs.pico-sdk.override {
    withSubmodules = true;
  };

  # Custom python environment with all dependencies included
  python-env = pkgs.python312.withPackages (pypkgs: with pypkgs; [
    pip
    numpy
    websockets
    pydantic
    smbus2
    scipy
    pyserial-asyncio
  ] ++ [
    (pkgs.python312Packages.buildPythonPackage rec {
      pname = "numpydantic";
      version = "1.7.0";
      format = "pyproject";
      src = pkgs.fetchPypi {
        inherit pname version;
        hash = "sha256-JoKFvuAm2d/fI+/u4T9gw7ddR94v/fLli08MF6aCTjs=";
      };
      nativeBuildInputs = with pkgs.python312Packages; [ pdm-backend ];
      propagatedBuildInputs = with pkgs.python312Packages; [ pydantic numpy ];
      doCheck = false;
    })
    (pkgs.python312Packages.buildPythonPackage {
      pname = "bmi270";
      version = "0.4.3";
      format = "other";
      src = pkgs.fetchFromGitHub {
        owner = "CoRoLab-Berlin";
        repo = "bmi270_python";
        rev = "8309e687d6b346455833c5d0c2734eeb56e98789";
        hash = "sha256-IxkMWWcrsglFV5HGDMK0GBx5o0svNfRXqhW8/ZWpsUk=";
      };
      buildPhase = ":";
      installPhase = ''
        runHook preInstall
        install -d $out/${pkgs.python312.sitePackages}
        cp -r src/bmi270 $out/${pkgs.python312.sitePackages}/
        runHook postInstall
      '';
      doCheck = false;
    })
    (pkgs.python312Packages.buildPythonPackage {
      pname = "ms5837";
      version = "0.1.0";
      src = pkgs.fetchFromGitHub {
        owner = "bluerobotics";
        repo = "ms5837-python";
        rev = "02996d71d2f08339b3d317b3f4da0a83781c706e";
        hash = "sha256-LBwM9sTvr7IaBcY8PcsPZcAbNRWBa4hj7tUC4oOr4eM=";
      };
      doCheck = false;
    })
  ]);

  # Wrapper script to start the firmware
  startScript = pkgs.writeShellScriptBin "start" ''
    cd $HOME/firmware
    export PYTHONPATH=src
    exec ${python-env}/bin/python3 -c "from rov_firmware import start; start()"
  '';

  # Wrapper script to run the tools CLI
  toolsScript = pkgs.writeShellScriptBin "tools" ''
    cd $HOME/firmware
    export PYTHONPATH=src
    exec ${python-env}/bin/python3 -c "from tools import cli; cli()"
  '';
in
{
  # Nix state version
  system.stateVersion = "25.05";

  # Disable GUI options for packages
  nixpkgs.overlays = [
    (final: prev: {
      rpicam-apps = prev.rpicam-apps.override {
        withQtPreview = false;
        withEglPreview = false;
        withOpenCVPostProc = false;
      };
      libadwaita = prev.libadwaita.overrideAttrs (old: {
        doCheck = false;
      });
    })
  ];

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
    extraGroups = [ "wheel" "networkmanager" "video" "i2c" "plugdev" ];
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

  # Enable camera and I2C with a high baud rate
  hardware = {
    i2c.enable = true;
    raspberry-pi.config.all = {
      dt-overlays = {
        ${cameraModule} = {
          enable = true;
          params = {};
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
      options = {
        gpu_mem = {
          enable = true;
          value = 256;
        };
      };
    };
  };

  # Setup video streaming
  services.go2rtc = {
    enable = true;
    settings = {
      streams.cam =
        "exec:${pkgs.rpi.rpicam-apps}/bin/libcamera-vid -t 0 -n --inline --width 1440 --height 1080 --framerate 30 --codec h264 -o -";
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
      btop
      sysstat
      rpi.libcamera
      rpi.rpicam-apps
      i2c-tools
      cmake
      gnumake
      gcc-arm-embedded
      clang
      clang-tools
      uv
      picotool
      pico-sdk-with-submodules
      python-env
      startScript
      toolsScript
    ];
    sessionVariables = {
      PICO_SDK_PATH = "${pico-sdk-with-submodules}/lib/pico-sdk";
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
        file."microcontroller-firmware/dshot.uf2".source = pkgs.fetchurl {
          url = "https://github.com/manafishrov/microcontroller-firmware/releases/download/v1.0.0-beta.1/dshot.uf2";
          sha256 = "0lj0hgivshc2nh0m1lxg2ks4821203q2zrw4qd81kvk1vqldzylr";
        };
        file."microcontroller-firmware/pwm.uf2".source = pkgs.fetchurl {
          url = "https://github.com/manafishrov/microcontroller-firmware/releases/download/v1.0.0-beta.1/pwm.uf2";
          sha256 = "0kmyf5imy6909412nzi87qwxkz5z8z0acxk4vghlw6fb2gwd4wn0";
        };
        activation.setupFirmware = home-manager.lib.hm.dag.entryAfter ["writeBoundary"] ''
          if [ ! -f "$HOME/.firmware_setup" ]; then
            mkdir -p $HOME/firmware
            cp -r ${./.}/* $HOME/firmware/
            chmod -R u+w $HOME/firmware
            touch "$HOME/.firmware_setup"
          fi
        '';
      };
    };
  };

  # Services
  systemd.services = {
    manafish-firmware = {
      enable = true;
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" "go2rtc.service" ];
      serviceConfig = {
        Type = "simple";
        User = "pi";
        WorkingDirectory = "/home/pi/firmware";
        ExecStart = "${startScript}/bin/start";
        Restart = "always";
        RestartSec = "5";
      };
    };
  };
}
