{
  pkgs,
  inputs,
  mcuFirmwareVersion,
  escFirmwareVersion,
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
    extraGroups = ["wheel" "networkmanager" "video" "i2c" "gpio" "plugdev"];
    password = "manafish";
    home = homeDir;
  };

  environment.systemPackages = with pkgs; [
    neovim
    nano
    helix
  ];

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
      ESC_FIRMWARE_DIR="${homeDir}/esc-firmware"
      CONFIG="$FIRMWARE_DIR/src/rov_firmware/config.json"
      MARKER="$FIRMWARE_DIR/.nix-source"
      CURRENT_SOURCE="${firmwareSource}"

      if [ ! -f "$MARKER" ] || [ "$(cat "$MARKER")" != "$CURRENT_SOURCE" ]; then
        CONFIG_BACKUP="${homeDir}/.config-backup.json"
        [ -f "$CONFIG" ] && cp "$CONFIG" "$CONFIG_BACKUP"
        rm -rf "$FIRMWARE_DIR"
        cp -r "$CURRENT_SOURCE" "$FIRMWARE_DIR"
        chmod -R u+w "$FIRMWARE_DIR"
        echo "$CURRENT_SOURCE" > "$MARKER"
        [ -f "$CONFIG_BACKUP" ] && mv "$CONFIG_BACKUP" "$CONFIG"
      fi

      mkdir -p "$MCU_DIR"
      for board in pico pico2; do
        TARGET="$MCU_DIR/$board-${mcuFirmwareVersion}.uf2"
        find "$MCU_DIR" -maxdepth 1 -type f -name "$board-v*.uf2" ! -name "$(basename "$TARGET")" -delete
        [ -f "$TARGET" ] && continue
        case "$board" in
          pico)  cp ${inputs.mcu-firmware-pico} "$TARGET" ;;
          pico2) cp ${inputs.mcu-firmware-pico2} "$TARGET" ;;
        esac
        chmod u+w "$TARGET"
      done

      mkdir -p "$ESC_FIRMWARE_DIR"
      ESC_FIRMWARE_TARGET="$ESC_FIRMWARE_DIR/esc-${escFirmwareVersion}.hex"
      find "$ESC_FIRMWARE_DIR" -maxdepth 1 -type f \( -name "esc-v*.hex" -o -name "esc-v*.bin" \) ! -name "$(basename "$ESC_FIRMWARE_TARGET")" -delete
      if [ ! -f "$ESC_FIRMWARE_TARGET" ]; then
        cp ${inputs.esc-firmware} "$ESC_FIRMWARE_TARGET"
        chmod u+w "$ESC_FIRMWARE_TARGET"
      fi
    '';
  };
}
