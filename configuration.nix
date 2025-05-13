{ pkgs, nixos-hardware, ... }:
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
  boot.kernelModules = [ "bcm2835-v4l2" "i2c-bcm2835" ];
  imports = [
    "${nixos-hardware}/raspberry-pi/4/pkgs-overlays.nix"
  ];
  hardware = {
    i2c.enable = true; # Adds "i2c-dev" kernel module and creates i2c group
    raspberry-pi."4".apply-overlays-dtmerge.enable = true; # This and the overlays import make the device tree overlays work (it is not specific to the 4 even though it is labeled as such)
    deviceTree = {
      enable = true;
      filter = "bcm2837-rpi-3*";
      overlays = [
        {
          name = "i2c1";
          dtsText = ''
            /dts-v1/;
            /plugin/;

            / {
              compatible = "brcm,bcm2837";

              fragment@0 {
                target = <&i2c1>;
                __overlay__ {
                  status = "okay";
                  clock-frequency = <1000000>;
                };
              };
            };
          '';
        }
        {
          name = "ov5647";
          dtsText = ''
          /dts-v1/;
          /plugin/;

          / {
            compatible = "brcm,bcm2837";

            i2c_frag: fragment@0 {
                target = <&i2c_csi_dsi>;
                __overlay__ {
                    #address-cells = <1>;
                    #size-cells = <0>;
                    status = "okay";

                    cam_node: ov5647@36 {
                        compatible = "ovti,ov5647";
                        reg = <0x36>;
                        status = "disabled";

                        clocks = <&cam1_clk>;

                        avdd-supply = <&cam1_reg>;
                        dovdd-supply = <&cam_dummy_reg>;
                        dvdd-supply = <&cam_dummy_reg>;

                        rotation = <0>;
                        orientation = <2>;

                        port {
                            cam_endpoint: endpoint {
                                clock-lanes = <0>;
                                data-lanes = <1 2>;
                                clock-noncontinuous;
                                link-frequencies =
                                    /bits/ 64 <297000000>;
                            };
                        };
                    };

                    vcm_node: ad5398@c {
                        compatible = "adi,ad5398";
                        reg = <0x0c>;
                        status = "disabled";
                        VANA-supply = <&cam1_reg>;
                    };
                };
            };

            csi_frag: fragment@1 {
                target = <&csi1>;
                csi: __overlay__ {
                    status = "okay";
                    brcm,media-controller;

                    port {
                        csi_ep: endpoint {
                            remote-endpoint = <&cam_endpoint>;
                            data-lanes = <1 2>;
                        };
                    };
                };
            };

            fragment@2 {
                target = <&i2c0if>;
                __overlay__ {
                    status = "okay";
                };
            };

            fragment@3 {
                target = <&i2c0mux>;
                __overlay__ {
                    status = "okay";
                };
            };

            reg_frag: fragment@4 {
                target = <&cam1_reg>;
                __overlay__ {
                    startup-delay-us = <20000>;
                };
            };

            clk_frag: fragment@5 {
                target = <&cam1_clk>;
                __overlay__ {
                    status = "okay";
                    clock-frequency = <25000000>;
                };
            };

            __overrides__ {
                rotation = <&cam_node>,"rotation:0";
                orientation = <&cam_node>,"orientation:0";
                media-controller = <&csi>,"brcm,media-controller?";
                cam0 = <&i2c_frag>, "target:0=",<&i2c_csi_dsi0>,
                      <&csi_frag>, "target:0=",<&csi0>,
                      <&reg_frag>, "target:0=",<&cam0_reg>,
                      <&clk_frag>, "target:0=",<&cam0_clk>,
                      <&cam_node>, "clocks:0=",<&cam0_clk>,
                      <&cam_node>, "avdd-supply:0=",<&cam0_reg>,
                      <&vcm_node>, "VANA-supply:0=",<&cam0_reg>;
                vcm = <&vcm_node>, "status=okay",
                      <&cam_node>,"lens-focus:0=", <&vcm_node>;
            };
          };

          &cam_node {
            status = "okay";
          };

          &cam_endpoint {
            remote-endpoint = <&csi_ep>;
          };
        '';
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
