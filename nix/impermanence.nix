{
  lib,
  config,
  ...
}: let
  piUser = config.users.users.pi;
in {
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
        group = piUser.group;
        mode = "u=rwx,g=,o=";
      }
      "/var/log"
      "/var/lib/nixos"
      "/var/lib/systemd"
      "/var/lib/NetworkManager"
      "/var/lib/iwd"
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
}
