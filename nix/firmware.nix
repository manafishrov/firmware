{
  pkgs,
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
    export PICOTOOL_PATH="${pkgs.lib.getExe pkgs.picotool}"
    export PATH="${pkgs.lib.makeBinPath [pkgs.picotool]}:$PATH"
    exec ${python-env}/bin/python3 -c "from rov_firmware import start; start()"
  '';

  toolsScript = pkgs.writeShellScriptBin "tools" ''
    cd $HOME/firmware
    export PYTHONPATH=src
    export PICOTOOL_PATH="${pkgs.lib.getExe pkgs.picotool}"
    export PATH="${pkgs.lib.makeBinPath [pkgs.picotool]}:$PATH"
    exec ${python-env}/bin/python3 -c "from tools import cli; cli()"
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
  ];

  systemd.services.manafish-firmware = {
    enable = true;
    wantedBy = ["multi-user.target"];
    after = ["network.target" "go2rtc.service"];
    serviceConfig = {
      Type = "simple";
      User = "pi";
      WorkingDirectory = "/home/pi/firmware";
      ExecStart = "${startScript}/bin/start";
      Restart = "always";
      RestartSec = "5";
    };
  };
}
