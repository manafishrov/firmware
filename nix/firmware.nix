{
  config,
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

    UPDATE_DIR="/home/pi/.cache/manafish-firmware-update"
    REQUEST="$UPDATE_DIR/request.json"
    STATUS="$UPDATE_DIR/status.json"
    PUBLIC_KEY="RWQ79VrKeNgtcTOSQWqd8vI9zVSZbrzXzuUNUzht6ZpHwRLLnUZPSl8s"

    write_status() {
      local phase="$1"
      local message="''${2:-}"
      PHASE="$phase" MESSAGE="$message" STATUS="$STATUS" ${lib.getExe' python-env "python3"} -c 'import json, os; from pathlib import Path; Path(os.environ["STATUS"]).write_text(json.dumps({"phase": os.environ["PHASE"], "message": os.environ["MESSAGE"]}), encoding="utf-8")'
    }

    fail() {
      write_status failed "$1"
      exit 1
    }

    read_field() {
      local field="$1"
      FIELD="$field" REQUEST="$REQUEST" ${lib.getExe' python-env "python3"} -c 'import json, os; print(json.load(open(os.environ["REQUEST"], encoding="utf-8"))[os.environ["FIELD"]])'
    }

    [ -f "$REQUEST" ] || fail "No firmware update request found."

    CLOSURE_PATH="$(read_field closurePath)"
    SIGNATURE_PATH="$(read_field signaturePath)"
    SYSTEM_PATH="$(read_field systemPath)"

    case "$CLOSURE_PATH" in
      "$UPDATE_DIR"/*.closure.zst) ;;
      *) fail "Firmware closure path is outside the update staging directory." ;;
    esac
    case "$SIGNATURE_PATH" in
      "$UPDATE_DIR"/*.closure.zst.minisig) ;;
      *) fail "Firmware signature path is outside the update staging directory." ;;
    esac
    case "$SYSTEM_PATH" in
      /nix/store/*-nixos-system-*) ;;
      *) fail "Firmware system path is not a NixOS system closure." ;;
    esac

    [ -f "$CLOSURE_PATH" ] || fail "Firmware closure is missing."
    [ -f "$SIGNATURE_PATH" ] || fail "Firmware signature is missing."
    [ ! -L "$CLOSURE_PATH" ] || fail "Firmware closure must not be a symlink."
    [ ! -L "$SIGNATURE_PATH" ] || fail "Firmware signature must not be a symlink."

    write_status verifying "Verifying firmware update signature."
    ${lib.getExe pkgs.minisign} -Vm "$CLOSURE_PATH" -P "$PUBLIC_KEY" -x "$SIGNATURE_PATH" \
      || fail "Firmware signature verification failed."

    write_status importing "Importing firmware closure."
    IMPORTED_PATHS="$(${lib.getExe pkgs.zstd} -dc "$CLOSURE_PATH" | ${config.nix.package}/bin/nix-store --import)" \
      || fail "Firmware closure import failed."

    printf '%s\n' "$IMPORTED_PATHS" | ${lib.getExe pkgs.gnugrep} -Fx "$SYSTEM_PATH" >/dev/null \
      || fail "Firmware system path was not present in imported closure."
    [ -x "$SYSTEM_PATH/bin/switch-to-configuration" ] \
      || fail "Firmware activation command is missing."

    write_status activating "Activating firmware system generation."
    "$SYSTEM_PATH/bin/switch-to-configuration" switch \
      || fail "Firmware system activation failed."

    write_status activated "Firmware update activated; waiting for MCU firmware verification."
    rm -f "$CLOSURE_PATH" "$SIGNATURE_PATH" "$REQUEST"
    ${pkgs.systemd}/bin/systemctl restart manafish-setup.service || true
    ${pkgs.systemd}/bin/systemctl restart manafish-firmware.service || true
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

  systemd.tmpfiles.rules = [
    "d /home/pi/.cache/manafish-firmware-update 0755 pi users - -"
  ];

  systemd.services.manafish-firmware = {
    enable = true;
    wantedBy = ["multi-user.target"];
    after = ["manafish-setup.service" "manafish-network.service" "go2rtc.service"];
    requires = ["manafish-setup.service"];
    serviceConfig = {
      Type = "simple";
      User = "pi";
      WorkingDirectory = "/home/pi/firmware";
      ExecStart = lib.getExe startScript;
      Restart = "always";
      RestartSec = "5";
    };
  };

  systemd.paths.manafish-firmware-update = {
    wantedBy = ["multi-user.target"];
    pathConfig = {
      PathChanged = "/home/pi/.cache/manafish-firmware-update/request.json";
      Unit = "manafish-firmware-update.service";
    };
  };

  systemd.services.manafish-firmware-update = {
    serviceConfig = {
      Type = "oneshot";
      User = "root";
    };
    script = ''
      ${lib.getExe firmwareUpdateInstaller}
    '';
  };
}
