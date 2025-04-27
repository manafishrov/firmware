{ pkgs, config, ... }:
{
  imports = [
    <nixos-hardware/raspberry-pi/4/pkgs-overlays.nix>
  ];
  nixpkgs.overlays = [
    (self: super: {
      libcamera = super.libcamera.overrideAttrs ({ patches ? [ ], ... }: {
        patches = patches ++ [
          (self.fetchpatch {
            url = "https://patchwork.libcamera.org/patch/19420/raw";
            hash = "sha256-xJ8478CAKvyo2k1zrfIytDxFQ1Qdd8ilMdABQoNcdPU=";
          })
        ];
      });
    })
  ];
  hardware = {
    raspberry-pi."4".apply-overlays-dtmerge.enable = true;
    deviceTree = {
      enable = true;
      filter = "bcm2837-rpi*.dtb";
      overlays =
        let
          mkCompatibleDtsFile = dtbo:
            let
              drv = (pkgs.runCommand (builtins.replaceStrings [ ".dtbo" ] [ ".dts" ] (baseNameOf dtbo)) {
                nativeBuildInputs = with pkgs; [ dtc gnused ];
              }) ''
                mkdir "$out"
                dtc -I dtb -O dts '${dtbo}' | sed -e 's/bcm2835/bcm2837/' > "$out/overlay.dts"
              '';
            in
            "${drv}/overlay.dts";
        in
        [
          {
            name = "imx708";
            dtsFile =
              mkCompatibleDtsFile "${config.boot.kernelPackages.kernel}/dtbs/overlays/imx708.dtbo";
          }
          {
            name = "vc4-fkms-v3d";
            dtsFile = mkCompatibleDtsFile "${config.boot.kernelPackages.kernel}/dtbs/overlays/vc4-fkms-v3d.dtbo";
          }
        ];
    };
  };
  services.udev.extraRules = ''
    SUBSYSTEM=="dma_heap", GROUP="video", MODE="0660"
  '';
}
