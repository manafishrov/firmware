{
  pkgs,
  lib,
  ...
}: let
  fwEnvConfig = pkgs.writeText "fw_env.config" ''
    /dev/mmcblk0	0x80000		0x40000
    /dev/mmcblk0	0xC0000		0x40000
  '';
in {
  environment = {
    systemPackages = [pkgs.curl pkgs.ubootTools];
    etc = {
      "rauc/keyring.pem".source = ../rauc-keyring.pem;
      "fw_env.config".source = fwEnvConfig;
    };
  };

  services.rauc = {
    enable = true;
    client.enable = true;
    compatible = "manafishrov-pi3";
    bootloader = "uboot";
    dataDir = "/persistent/rauc";
    bundleFormats = ["+verity" "-plain"];

    slots.rootfs = [
      {
        enable = true;
        device = "/dev/disk/by-partuuid/6d616e61-02";
        type = "ext4";
        settings.bootname = "A";
      }
      {
        enable = true;
        device = "/dev/disk/by-partuuid/6d616e61-03";
        type = "ext4";
        settings.bootname = "B";
      }
    ];

    settings.keyring.path = "/etc/rauc/keyring.pem";
  };

  systemd.services.rauc-mark-good = {
    description = "Mark the booted RAUC slot as good after the firmware health check passes";
    wantedBy = ["multi-user.target"];
    after = [
      "manafish-firmware.service"
      "network-online.target"
    ];
    wants = ["network-online.target"];
    requires = ["manafish-firmware.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      User = "root";
    };
    script = ''
      set -euo pipefail

      booted=$(${lib.getExe pkgs.rauc} status booted 2>/dev/null \
        | ${lib.getExe pkgs.gnugrep} -oE 'rootfs\.[01]' \
        | head -n1 || true)

      if [ -z "$booted" ]; then
        echo "Could not determine booted slot; skipping mark-good." >&2
        exit 0
      fi

      for attempt in $(seq 1 60); do
        if ${lib.getExe pkgs.curl} -fsS --max-time 3 \
            http://127.0.0.1:9100/firmware/health > /dev/null; then
          ${lib.getExe pkgs.rauc} status mark-good booted
          ${lib.getExe' pkgs.coreutils "install"} -d -m 0755 /var/lib/manafish-firmware-update
          printf '{"phase":"completed","message":"Firmware activated.","percent":100}\n' \
            > /var/lib/manafish-firmware-update/status.json
          exit 0
        fi
        sleep 1
      done

      echo "Health probe never returned 200 within 60s; leaving slot in trial state." >&2
      exit 1
    '';
  };

  systemd.services.rauc-rollback-detector = {
    description = "Detect post-update rollback and surface it to the app via status.json";
    wantedBy = ["multi-user.target"];
    after = ["manafish-firmware.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      User = "root";
    };
    script = ''
      set -euo pipefail

      expected=/persistent/rauc/expected-slot
      if [ ! -f "$expected" ]; then
        exit 0
      fi

      expected_slot=$(${lib.getExe' pkgs.coreutils "cat"} "$expected")
      booted=$(${lib.getExe pkgs.gnugrep} -oE 'rauc\.slot=[A-Z]' /proc/cmdline \
        | ${lib.getExe' pkgs.coreutils "cut"} -d= -f2 || true)

      if [ -n "$booted" ] && [ "$booted" != "$expected_slot" ]; then
        ${lib.getExe' pkgs.coreutils "install"} -d -m 0755 /var/lib/manafish-firmware-update
        ${pkgs.python313}/bin/python3 -c "
      import json, pathlib
      pathlib.Path('/var/lib/manafish-firmware-update/status.json').write_text(
          json.dumps({
              'phase': 'rolled-back',
              'message': 'Update was reverted by automatic rollback.',
              'percent': 100,
          })
      )
      "
      fi

      ${lib.getExe' pkgs.coreutils "rm"} -f "$expected"
    '';
  };
}
