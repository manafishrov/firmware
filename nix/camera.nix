{
  pkgs,
  lib,
  ...
}: {
  nixpkgs.overlays = [
    (_: prev: {
      rpicam-apps = prev.rpicam-apps.override {
        withQtPreview = false;
        withEglPreview = false;
        withOpenCVPostProc = false;
      };
    })
  ];

  hardware.raspberry-pi.config.all = {
    dt-overlays.imx477 = {
      enable = true;
      params = {};
    };
    base-dt-params.camera_auto_detect = {
      enable = true;
      value = false;
    };
  };

  environment.systemPackages = with pkgs; [
    rpi.libcamera
    rpi.rpicam-apps
  ];

  services.go2rtc = {
    enable = true;
    settings = {
      streams.cam = "exec:${lib.getExe' pkgs.rpi.rpicam-apps "rpicam-vid"} -t 0 -n --inline -o -";
      api = {
        listen = ":1984";
        origin = "*";
      };
      webrtc.listen = ":8555";
      rtsp.listen = "";
      rtmp.listen = "";
    };
  };
}
