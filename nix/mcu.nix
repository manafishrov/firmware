{pkgs, ...}: let
  pico-sdk-with-submodules = pkgs.pico-sdk.override {
    withSubmodules = true;
  };
in {
  # Expose the Pico's USB CDC serial interface as /dev/ttyACM*.
  boot.kernelModules = ["cdc_acm"];

  # Grant pi user access to the MCU and RP-series BOOTSEL devices.
  services.udev.extraRules = ''
    ATTRS{manufacturer}=="Raspberry Pi", MODE="660", GROUP="plugdev", TAG+="uaccess"
  '';

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
