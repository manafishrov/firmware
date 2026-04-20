{
  pkgs,
  inputs,
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

  # Deploy firmware files and MCU firmware to the user's home directory.
  # Uses a systemd service instead of home-manager because the SD image
  # builder does not populate the nix database, which home-manager requires.
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
      BACKUP="$FIRMWARE_DIR/src/rov_firmware/config-backup.json"

      [ -f "$CONFIG" ] && cp "$CONFIG" "$BACKUP"
      rm -rf "$FIRMWARE_DIR"
      cp -r ${firmwareSource} "$FIRMWARE_DIR"
      chmod -R u+w "$FIRMWARE_DIR"
      [ -f "$BACKUP" ] && mv "$BACKUP" "$CONFIG"

      mkdir -p "$MCU_DIR"
      for fw in ${inputs.mcu-firmware-pico} ${inputs.mcu-firmware-pico2}; do
        name="$(basename "$fw")"
        cp "$fw" "$MCU_DIR/''${name:33}"
      done
      chmod u+w "$MCU_DIR"/*.uf2
    '';
  };
}
