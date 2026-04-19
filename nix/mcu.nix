{pkgs, ...}: let
  pico-sdk-with-submodules = pkgs.pico-sdk.override {
    withSubmodules = true;
  };
in {
  environment = {
    systemPackages = with pkgs; [
      cmake
      gnumake
      gcc-arm-embedded
      clang
      clang-tools
      picotool
      pico-sdk-with-submodules
    ];
    sessionVariables = {
      PICO_SDK_PATH = "${pico-sdk-with-submodules}/lib/pico-sdk";
    };
  };
}
