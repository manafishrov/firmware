{
  pkgs,
  home-manager,
  camera,
  inputs,
  ...
}: let
  pico-sdk-with-submodules = pkgs.pico-sdk.override {
    withSubmodules = true;
  };

  # Custom python environment with all dependencies included
  python-env = pkgs.python313.withPackages (pypkgs:
    with pypkgs;
      [
        pip
        numpy
        websockets
        pydantic
        smbus2
        scipy
        pyserial-asyncio-fast
      ]
      ++ [
        (pkgs.python313Packages.buildPythonPackage {
          pname = "numpydantic";
          version = "1.7.0";
          format = "pyproject";
          src = inputs.numpydantic-src;
          nativeBuildInputs = with pkgs.python313Packages; [pdm-backend];
          propagatedBuildInputs = with pkgs.python313Packages; [pydantic numpy];
          doCheck = false;
        })
        (pkgs.python313Packages.buildPythonPackage {
          pname = "bmi270";
          version = "0.4.3";
          format = "other";
          src = inputs.bmi270-src;
          buildPhase = ":";
          installPhase = ''
            runHook preInstall
            install -d $out/${pkgs.python313.sitePackages}
            cp -r src/bmi270 $out/${pkgs.python313.sitePackages}/
            runHook postInstall
          '';
          doCheck = false;
        })
        (pkgs.python313Packages.buildPythonPackage {
          pname = "ms5837";
          version = "0.1.0";
          format = "pyproject";
          src = inputs.ms5837-src;
          nativeBuildInputs = with pkgs.python313Packages; [setuptools wheel];
          propagatedBuildInputs = with pkgs.python313Packages; [smbus2];
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
in {
  # Nix state version
  system.stateVersion = "25.11";

  # Disable GUI options for packages
  nixpkgs.overlays = [
    (_: prev: {
      rpicam-apps = prev.rpicam-apps.override {
        withQtPreview = false;
        withEglPreview = false;
        withOpenCVPostProc = false;
      };
      libadwaita = prev.libadwaita.overrideAttrs (_: {
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
    extraGroups = ["wheel" "networkmanager" "video" "i2c" "plugdev"];
    password = "manafish";
    home = "/home/pi";
  };

  # Networking configuration
  networking = {
    hostName = "manafish";
    interfaces.eth0.ipv4.addresses = [
      {
        address = "10.10.10.10";
        prefixLength = 24;
      }
    ];
    # Disable firewall so all ports are open to allow easy configuration
    firewall.enable = false;
    nftables.enable = false;
    # Enable Wi-Fi
    wireless.iwd.enable = true;
    networkmanager = {
      enable = true;
      wifi.backend = "iwd";
    };
  };

  # Enable camera and I2C with a high baud rate
  hardware = {
    i2c.enable = true;
    raspberry-pi.config.all = {
      dt-overlays = {
        ${camera} = {
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
    };
  };

  # Services
  services = {
    # mDNS to connect via manafish.local
    avahi = {
      enable = true;
      nssmdns4 = true;
      allowInterfaces = ["eth0"];
      publish = {
        enable = true;
        addresses = true;
      };
    };

    # Enable SSH
    openssh = {
      enable = true;
      settings.PasswordAuthentication = true;
    };

    # Setup video streaming
    go2rtc = {
      enable = true;
      settings = {
        streams.cam = "exec:${pkgs.rpi.rpicam-apps}/bin/rpicam-vid -t 0 -n --inline --width 1440 --height 1080 --framerate 30 --codec h264 -o -";
        api = {
          listen = ":1984";
          origin = "*";
        };
        webrtc.listen = ":8555";
        rtsp.listen = "";
        rtmp.listen = "";
      };
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
        stateVersion = "25.11";
        packages = with pkgs; [
          neovim
          nano
        ];
        file = {
          LICENSE.source = ./LICENSE;
          "microcontroller-firmware/dshot.uf2".source = pkgs.fetchurl {
            url = "https://github.com/manafishrov/microcontroller-firmware/releases/download/v1.0.0-beta.1/dshot.uf2";
            sha256 = "0lj0hgivshc2nh0m1lxg2ks4821203q2zrw4qd81kvk1vqldzylr";
          };
          "microcontroller-firmware/pwm.uf2".source = pkgs.fetchurl {
            url = "https://github.com/manafishrov/microcontroller-firmware/releases/download/v1.0.0-beta.1/pwm.uf2";
            sha256 = "0kmyf5imy6909412nzi87qwxkz5z8z0acxk4vghlw6fb2gwd4wn0";
          };
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
      wantedBy = ["multi-user.target"];
      after = ["network.target" "go2rtc.service"];
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
