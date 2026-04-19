{
  pkgs,
  inputs,
  ...
}: {
  nixpkgs.overlays = [
    (_: prev: {
      libadwaita = prev.libadwaita.overrideAttrs (_: {
        doCheck = false;
      });
    })
  ];

  systemd.tmpfiles.rules = [
    "d /nix/var/nix/profiles/per-user/pi 0755 pi root -"
  ];

  users.users.pi = {
    isNormalUser = true;
    extraGroups = ["wheel" "networkmanager" "video" "i2c" "plugdev"];
    password = "manafish";
    home = "/home/pi";
  };

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
          "mcu-firmware/pico.uf2".source = inputs.mcu-firmware-pico;
          "mcu-firmware/pico2.uf2".source = inputs.mcu-firmware-pico2;
        };
        activation.setupFirmware = inputs.home-manager.lib.hm.dag.entryAfter ["writeBoundary"] ''
          if [ "$CURRENT_VERSION" != "$INSTALLED_VERSION" ]; then
            mkdir -p $HOME/firmware
            CONFIG="$HOME/firmware/src/rov_firmware/config.json"
            BACKUP="$HOME/firmware/src/rov_firmware/config-backup.json"
            [ -f "$CONFIG" ] && cp "$CONFIG" "$BACKUP"
            cp -r ${./..}/* $HOME/firmware/
            chmod -R u+w $HOME/firmware
            [ -f "$BACKUP" ] && mv "$BACKUP" "$CONFIG"
            echo "$CURRENT_VERSION" > "$HOME/.firmware_version"
          fi
        '';
      };
    };
  };
}
