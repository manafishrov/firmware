{
  pkgs,
  inputs,
  mcuFirmwareVersion,
  ...
}: let
  username = "pi";
  homeDir = "/home/${username}";
  firmwareSource = ./..;
in {
  nixpkgs.overlays = [
    (_: prev: {
      libadwaita = prev.libadwaita.overrideAttrs (_: {
        doCheck = false;
      });
    })
  ];

  users.users.${username} = {
    isNormalUser = true;
    extraGroups = ["wheel" "networkmanager" "video" "i2c" "plugdev"];
    password = "manafish";
    home = homeDir;
  };

  environment.systemPackages = with pkgs; [
    neovim
    nano
  ];

  nix = {
    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 7d";
      persistent = true;
    };
    optimise = {
      automatic = true;
      dates = ["weekly"];
      persistent = true;
    };
  };

  # Deploy firmware files and MCU firmware to the user's home directory
  systemd.services.manafish-setup = {
    wantedBy = ["multi-user.target"];
    before = ["manafish-firmware.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      User = username;
    };
    script = ''
      FIRMWARE_DIR="${homeDir}/firmware"
      MCU_DIR="${homeDir}/mcu-firmware"
      CONFIG="$FIRMWARE_DIR/src/rov_firmware/config.json"
      CUSTOM_ACTIONS="$FIRMWARE_DIR/src/rov_firmware/custom_actions"
      MARKER="$FIRMWARE_DIR/.nix-source"
      CURRENT_SOURCE="${firmwareSource}"

      if [ ! -f "$MARKER" ] || [ "$(cat "$MARKER")" != "$CURRENT_SOURCE" ]; then
        TEMP_DIR="$(${pkgs.coreutils}/bin/mktemp -d)"
        CONFIG_BACKUP="$TEMP_DIR/config.json"
        CUSTOM_ACTIONS_BACKUP="$TEMP_DIR/custom_actions"
        [ -f "$CONFIG" ] && cp "$CONFIG" "$CONFIG_BACKUP"
        [ -d "$CUSTOM_ACTIONS" ] && cp -a "$CUSTOM_ACTIONS" "$CUSTOM_ACTIONS_BACKUP"

        rm -rf "$FIRMWARE_DIR"
        cp -r "$CURRENT_SOURCE" "$FIRMWARE_DIR"
        chmod -R u+w "$FIRMWARE_DIR"
        echo "$CURRENT_SOURCE" > "$MARKER"
        [ -f "$CONFIG_BACKUP" ] && mv "$CONFIG_BACKUP" "$CONFIG"
        if [ -d "$CUSTOM_ACTIONS_BACKUP" ]; then
          rm -rf "$CUSTOM_ACTIONS"
          mv "$CUSTOM_ACTIONS_BACKUP" "$CUSTOM_ACTIONS"
        fi
        rm -rf "$TEMP_DIR"
      fi

      mkdir -p "$MCU_DIR"
      for board in pico pico2; do
        TARGET="$MCU_DIR/$board-${mcuFirmwareVersion}.uf2"
        [ -f "$TARGET" ] && continue
        case "$board" in
          pico)  cp ${inputs.mcu-firmware-pico} "$TARGET" ;;
          pico2) cp ${inputs.mcu-firmware-pico2} "$TARGET" ;;
        esac
        chmod u+w "$TARGET"
      done
    '';
  };
}
