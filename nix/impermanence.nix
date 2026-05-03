{
  lib,
  config,
  pkgs,
  ...
}: let
  piUser = config.users.users.pi;
in {
  sdImage.expandOnBoot = false;

  fileSystems = {
    "/" = lib.mkForce {
      device = "none";
      fsType = "tmpfs";
      options = ["defaults" "size=512M" "mode=755"];
    };
    "/persistent" = {
      device = "/dev/disk/by-label/NIXOS_SD";
      fsType = "ext4";
      neededForBoot = true;
    };
    "/nix" = {
      device = "/persistent/nix";
      options = ["bind"];
      neededForBoot = true;
    };
  };

  environment.persistence."/persistent" = {
    hideMounts = true;
    directories = [
      {
        directory = piUser.home;
        user = piUser.name;
        inherit (piUser) group;
        mode = "u=rwx,g=,o=";
      }
      "/var/log"
      "/var/lib/nixos"
      "/var/lib/systemd"
      "/var/lib/NetworkManager"
      "/var/lib/iwd"
      {
        directory = "/var/lib/manafish-firmware-update";
        user = piUser.name;
        inherit (piUser) group;
        mode = "u=rwx,g=rx,o=";
      }
    ];
    files = [
      "/etc/machine-id"
      "/etc/ssh/ssh_host_ed25519_key"
      "/etc/ssh/ssh_host_ed25519_key.pub"
    ];
  };

  systemd.tmpfiles.rules = [
    "z /etc/ssh/ssh_host_ed25519_key 0600 root root -"
    "z /etc/ssh/ssh_host_ed25519_key.pub 0644 root root -"
  ];

  systemd.services.grow-persistent = {
    description = "Grow persistent SD card partition";
    wantedBy = ["multi-user.target"];
    after = ["local-fs.target"];
    before = ["manafish-setup.service" "manafish-firmware.service"];
    unitConfig.ConditionPathExists = "!/persistent/.partition-expanded";
    serviceConfig = {
      Type = "oneshot";
    };
    script = ''
      set -euo pipefail

      persistent_part="/dev/disk/by-label/NIXOS_SD"
      stamp="/persistent/.partition-expanded"
      boot_device="$(${lib.getExe' pkgs.util-linux "lsblk"} -npo PKNAME "$persistent_part")"
      part_number="$(${lib.getExe' pkgs.util-linux "lsblk"} -npo PARTN "$persistent_part")"

      if [ -z "$boot_device" ] || [ -z "$part_number" ]; then
        echo "Could not resolve persistent partition parent device; skipping grow."
        exit 0
      fi

      echo ",+," | ${lib.getExe' pkgs.util-linux "sfdisk"} -N"$part_number" --no-reread "$boot_device"
      ${lib.getExe' pkgs.parted "partprobe"} "$boot_device" || true
      ${lib.getExe' pkgs.systemd "udevadm"} settle || true
      ${lib.getExe' pkgs.e2fsprogs "resize2fs"} "$persistent_part"
      touch "$stamp"
    '';
  };
}
