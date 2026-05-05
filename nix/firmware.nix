{
  pkgs,
  lib,
  inputs,
  ...
}: let
  python-env = pkgs.python313.withPackages (pypkgs:
    with pypkgs;
      [
        pip
        numpy
        websockets
        pydantic
        smbus2
        scipy
        pyserial-asyncio-fast
      ]
      ++ [
        (pkgs.python313Packages.buildPythonPackage {
          pname = "numpydantic";
          version = "1.7.0";
          format = "pyproject";
          src = inputs.numpydantic-src;
          nativeBuildInputs = with pkgs.python313Packages; [pdm-backend];
          propagatedBuildInputs = with pkgs.python313Packages; [pydantic numpy];
          doCheck = false;
        })
        (pkgs.python313Packages.buildPythonPackage {
          pname = "bmi270";
          version = "0.4.3";
          format = "other";
          src = inputs.bmi270-src;
          buildPhase = ":";
          installPhase = ''
            runHook preInstall
            install -d $out/${pkgs.python313.sitePackages}
            cp -r src/bmi270 $out/${pkgs.python313.sitePackages}/
            runHook postInstall
          '';
          doCheck = false;
        })
        (pkgs.python313Packages.buildPythonPackage {
          pname = "ms5837";
          version = "0.1.0";
          format = "pyproject";
          src = inputs.ms5837-src;
          nativeBuildInputs = with pkgs.python313Packages; [setuptools wheel];
          propagatedBuildInputs = with pkgs.python313Packages; [smbus2];
          doCheck = false;
        })
      ]);

  startScript = pkgs.writeShellScriptBin "start" ''
    cd $HOME/firmware
    export PYTHONPATH=src
    export PICOTOOL_PATH="${lib.getExe pkgs.picotool}"
    export PATH="${lib.makeBinPath [pkgs.picotool]}:$PATH"
    exec ${lib.getExe' python-env "python3"} -c "from rov_firmware import start; start()"
  '';

  toolsScript = pkgs.writeShellScriptBin "tools" ''
    cd $HOME/firmware
    export PYTHONPATH=src
    export PICOTOOL_PATH="${lib.getExe pkgs.picotool}"
    export PATH="${lib.makeBinPath [pkgs.picotool]}:$PATH"
    exec ${lib.getExe' python-env "python3"} -c "from tools import cli; cli()"
  '';

  firmwareUpdateInstaller = pkgs.writeShellScriptBin "install-firmware-update" ''
    set -euo pipefail

    UPDATE_DIR="/var/lib/manafish-firmware-update"
    REQUEST="$UPDATE_DIR/request.json"
    STATUS="$UPDATE_DIR/status.json"
    EXPECTED_SLOT_FILE="/persistent/rauc/expected-slot"

    write_status() {
      local phase="$1"
      local message="''${2:-}"
      local percent="''${3:-0}"
      PHASE="$phase" MESSAGE="$message" PERCENT="$percent" STATUS="$STATUS" ${lib.getExe' python-env "python3"} -c 'import json, os; from pathlib import Path; Path(os.environ["STATUS"]).write_text(json.dumps({"phase": os.environ["PHASE"], "message": os.environ["MESSAGE"], "percent": int(os.environ["PERCENT"])}), encoding="utf-8")'
      chown pi:users "$STATUS"
      chmod 0640 "$STATUS"
    }

    cleanup_staged_bundle() {
      rm -f "''${BUNDLE_PATH:-}" "''${REQUEST:-}"
    }

    fail() {
      write_status failed "$1"
      cleanup_staged_bundle
      exit 1
    }

    read_field() {
      local field="$1"
      FIELD="$field" REQUEST="$REQUEST" ${lib.getExe' python-env "python3"} -c 'import json, os; print(json.load(open(os.environ["REQUEST"], encoding="utf-8"))[os.environ["FIELD"]])'
    }

    target_slot() {
      local booted target
      booted="$(${lib.getExe pkgs.rauc} status booted 2>/dev/null \
        | ${lib.getExe pkgs.gnugrep} -oE 'rootfs\.[01]' \
        | head -n1 || true)"
      case "$booted" in
        rootfs.0) target="B" ;;
        rootfs.1) target="A" ;;
        *) target="" ;;
      esac
      printf '%s\n' "$target"
    }

    [ -f "$REQUEST" ] || fail "No firmware update request found."

    BUNDLE_PATH="$(read_field bundlePath)"

    case "$BUNDLE_PATH" in
      "$UPDATE_DIR"/*.raucb) ;;
      *) fail "Firmware bundle path is outside the update staging directory." ;;
    esac

    [ -f "$BUNDLE_PATH" ] || fail "Firmware bundle is missing."
    [ ! -L "$BUNDLE_PATH" ] || fail "Firmware bundle must not be a symlink."

    write_status verifying "Verifying firmware bundle signature." 15

    write_status installing "Writing firmware bundle to inactive slot." 35
    ${lib.getExe pkgs.rauc} install "$BUNDLE_PATH" \
      || fail "RAUC install failed."

    expected="$(target_slot)"
    if [ -z "$expected" ]; then
      fail "Could not determine target slot after install."
    fi

    install -d -m 0755 -o root -g root /persistent/rauc
    printf '%s\n' "$expected" > "$EXPECTED_SLOT_FILE"

    write_status rebooting "Reboot required to activate new firmware." 95

    cleanup_staged_bundle
    ${lib.getExe' pkgs.systemd "systemctl"} reboot
  '';
in {
  environment.systemPackages = with pkgs; [
    htop
    btop
    sysstat
    uv
    python-env
    startScript
    toolsScript
    firmwareUpdateInstaller
  ];

  systemd = {
    tmpfiles.rules = [
      "d /var/lib/manafish-firmware-update 0750 pi users - -"
    ];

    services = {
      manafish-firmware = {
        enable = true;
        wantedBy = ["multi-user.target"];
        after = ["manafish-setup.service" "manafish-network.service" "go2rtc.service"];
        requires = ["manafish-setup.service"];
        serviceConfig = {
          Type = "simple";
          User = "pi";
          WorkingDirectory = "/home/pi/firmware";
          ExecStart = lib.getExe startScript;
          StateDirectory = "manafish-firmware-update";
          StateDirectoryMode = "0750";
          Restart = "always";
          RestartSec = "5";
        };
      };

      manafish-firmware-update = {
        unitConfig.Conflicts = ["manafish-firmware.service"];
        serviceConfig = {
          Type = "oneshot";
          User = "root";
          MemoryAccounting = true;
          MemoryHigh = "300M";
          MemoryMax = "500M";
          MemorySwapMax = "infinity";
          TasksMax = 64;
        };
        script = ''
          ${lib.getExe firmwareUpdateInstaller}
        '';
      };
    };

    paths.manafish-firmware-update = {
      wantedBy = ["multi-user.target"];
      pathConfig = {
        PathChanged = "/var/lib/manafish-firmware-update/request.json";
        Unit = "manafish-firmware-update.service";
      };
    };
  };
}
