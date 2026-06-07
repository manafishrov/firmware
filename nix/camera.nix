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
      # Low-latency WebRTC encode: Constrained Baseline (no B-frames), 20 Mbps,
      # one keyframe per second for fast recovery on late join / packet loss.
      streams.cam = "exec:${lib.getExe' pkgs.rpi.rpicam-apps "rpicam-vid"} -t 0 -n --inline --profile baseline --level 4.2 -b 20000000 --framerate 30 -g 30 -o -";
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
