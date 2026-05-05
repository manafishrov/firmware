{
  lib,
  config,
  pkgs,
  ...
}: let
  piUser = config.users.users.pi;
in {
  fileSystems = {
    "/" = lib.mkForce {
      device = "/dev/root";
      fsType = "ext4";
      options = ["noatime"];
    };
    "/boot/firmware" = lib.mkForce {
      device = "/dev/disk/by-label/FIRMWARE";
      fsType = "vfat";
      options = ["noatime" "noauto" "x-systemd.automount"];
    };
    "/persistent" = {
      device = "/dev/disk/by-label/PERSISTENT";
      fsType = "ext4";
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
      "/var/lib/rauc"
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
    "d /persistent/rauc 0755 root root -"
  ];

  systemd.services.grow-persistent = {
    description = "Grow the persistent partition to fill the SD card on first boot";
    wantedBy = ["multi-user.target"];
    after = ["systemd-udev-settle.service"];
    before = [
      "persistent.mount"
      "manafish-setup.service"
      "manafish-firmware.service"
    ];
    unitConfig = {
      DefaultDependencies = false;
      ConditionPathExists = "!/persistent/.partition-expanded";
    };
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    path = with pkgs; [util-linux parted e2fsprogs systemd coreutils];
    script = ''
      set -euo pipefail

      persistent_part="/dev/disk/by-label/PERSISTENT"
      stamp="/persistent/.partition-expanded"

      if ! [ -e "$persistent_part" ]; then
        echo "Persistent partition not yet present; udev not settled?" >&2
        exit 0
      fi

      boot_device="$(lsblk -npo PKNAME "$persistent_part")"
      part_number="$(lsblk -npo PARTN "$persistent_part")"

      if [ -z "$boot_device" ] || [ -z "$part_number" ]; then
        echo "Could not resolve persistent partition parent device; skipping grow."
        exit 0
      fi

      echo ",+," | sfdisk -N"$part_number" --no-reread "$boot_device"

      if ! partprobe "$boot_device"; then
        echo "partprobe rejected reread; rebooting once to pick up new partition table." >&2
        ${lib.getExe' pkgs.systemd "systemctl"} reboot
        exit 0
      fi

      udevadm settle || true
      resize2fs "$persistent_part"

      mount "$persistent_part" /persistent
      touch "$stamp"
      umount /persistent
    '';
  };
}
