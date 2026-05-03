{
  lib,
  config,
  pkgs,
  ...
}: let
  piUser = config.users.users.pi;
  minGrowBytes = 512 * 1024 * 1024;
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
    serviceConfig = {
      Type = "oneshot";
    };
    script = ''
      set -euo pipefail

      persistent_part="/dev/disk/by-label/NIXOS_SD"
      boot_device="$(${pkgs.util-linux}/bin/lsblk -npo PKNAME "$persistent_part")"
      part_number="$(${pkgs.util-linux}/bin/lsblk -npo PARTN "$persistent_part")"

      if [ -z "$boot_device" ] || [ -z "$part_number" ]; then
        echo "Could not resolve persistent partition parent device; skipping grow."
        exit 0
      fi

      disk_bytes="$(${pkgs.util-linux}/bin/blockdev --getsize64 "$boot_device")"
      part_bytes="$(${pkgs.util-linux}/bin/blockdev --getsize64 "$persistent_part")"
      available_growth=$((disk_bytes - part_bytes))

      if [ "$available_growth" -lt ${toString minGrowBytes} ]; then
        echo "Persistent partition already uses available SD card space."
        exit 0
      fi

      echo ",+," | ${pkgs.util-linux}/bin/sfdisk -N"$part_number" --no-reread "$boot_device"
      ${pkgs.parted}/bin/partprobe "$boot_device" || true
      ${pkgs.systemd}/bin/udevadm settle || true
      ${pkgs.e2fsprogs}/bin/resize2fs "$persistent_part"
    '';
  };
}
