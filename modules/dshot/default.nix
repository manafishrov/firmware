{ lib, pkgs, ... }:
let
  dshot-src = pkgs.fetchFromGitHub {
    owner = "Marian-Vittek";
    repo = "raspberry-pi-dshot";
    rev = "f7f0409359c39357c4d8353146d0eed72b1e86d3";
    hash = "";
  };

  dshot = pkgs.python3Packages.buildPythonPackage {
    pname = "dshot";
    version = "0.1";
    format = "setuptools";

    src = pkgs.runCommand "dshot-src" {} ''
      mkdir -p $out/dshot
      cp ${dshot-src}/motor-dshot.c $out/dshot/dshot.c
      cp ${./dshot/__init__.py} $out/__init__.py
      cp ${./setup.py} $out/setup.py
    '';

    buildInputs = with pkgs.python3Packages; [
      setuptools
    ];
    nativeBuildInputs = [ pkgs.gcc ];
    doCheck = false;
  };
in
{
  environment.systemPackages = [ (pkgs.python3.withPackages (pypkgs: [ dshot ])) ];
}
