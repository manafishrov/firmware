{
  pkgs,
  lib,
  ...
}: let
  jq = lib.getExe pkgs.jq;
  rpicamVid = lib.getExe' pkgs.rpi.rpicam-apps "rpicam-vid";
  systemctl = lib.getExe' pkgs.systemd "systemctl";

  # The camera settings live in the ROV config, which the firmware persists as
  # user `pi` with mode 0600. go2rtc therefore runs as `pi` (see below) so this
  # wrapper can read the file. Every value is validated with a safe fallback, so
  # a missing, unreadable, or corrupt config can never stop the stream from
  # starting.
  configPath = "/home/pi/firmware/src/rov_firmware/config.json";

  cameraStream = pkgs.writeShellScript "manafish-camera-stream" ''
    set -u

    CONFIG="${configPath}"

    # Read a single camera field. Always succeeds; prints empty on any error so
    # the caller falls back to its default.
    get() {
      ${jq} -r "$1 // empty" "$CONFIG" 2>/dev/null || true
    }

    # clamp_int VALUE MIN MAX DEFAULT -> integer within [MIN, MAX]
    clamp_int() {
      case "$1" in
        "" | *[!0-9]*)
          printf '%s' "$4"
          return
          ;;
      esac
      value=$1
      [ "$value" -lt "$2" ] && value=$2
      [ "$value" -gt "$3" ] && value=$3
      printf '%s' "$value"
    }

    # num_or VALUE DEFAULT -> VALUE if it looks like a decimal, else DEFAULT.
    # Upstream (app + firmware) already clamp ranges; this only guards syntax.
    num_or() {
      case "$1" in
        "" | *[!0-9.-]*) printf '%s' "$2" ;;
        *) printf '%s' "$1" ;;
      esac
    }

    # enum_or VALUE DEFAULT ALLOWED... -> VALUE if allowed, else DEFAULT.
    enum_or() {
      value=$1
      fallback=$2
      shift 2
      for allowed in "$@"; do
        if [ "$value" = "$allowed" ]; then
          printf '%s' "$value"
          return
        fi
      done
      printf '%s' "$fallback"
    }

    WIDTH=$(clamp_int "$(get .camera.width)" 160 4056 1920)
    HEIGHT=$(clamp_int "$(get .camera.height)" 160 3040 1080)
    FRAMERATE=$(clamp_int "$(get .camera.framerate)" 1 60 30)
    BITRATE=$(clamp_int "$(get .camera.bitrate)" 1000000 25000000 20000000)
    KEYFRAME_INTERVAL=$(clamp_int "$(get .camera.keyframeInterval)" 1 300 30)
    ROTATION=$(enum_or "$(get .camera.rotation)" 0 0 180)
    PROFILE=$(enum_or "$(get .camera.profile)" baseline baseline main high)
    LEVEL=$(enum_or "$(get .camera.level)" 4.2 4 4.1 4.2)
    AWB=$(enum_or "$(get .camera.awb)" auto \
      auto incandescent tungsten fluorescent indoor daylight cloudy)
    DENOISE=$(enum_or "$(get .camera.denoise)" auto \
      auto off cdn_off cdn_fast cdn_hq)
    EV=$(num_or "$(get .camera.exposureValue)" 0)
    BRIGHTNESS=$(num_or "$(get .camera.brightness)" 0)
    CONTRAST=$(num_or "$(get .camera.contrast)" 1)
    SATURATION=$(num_or "$(get .camera.saturation)" 1)
    SHARPNESS=$(num_or "$(get .camera.sharpness)" 1)
    HFLIP=$(get .camera.hflip)
    VFLIP=$(get .camera.vflip)

    set -- \
      -t 0 -n --inline \
      --width "$WIDTH" --height "$HEIGHT" --framerate "$FRAMERATE" \
      --codec h264 --profile "$PROFILE" --level "$LEVEL" \
      -b "$BITRATE" -g "$KEYFRAME_INTERVAL" \
      --rotation "$ROTATION" \
      --awb "$AWB" --ev "$EV" \
      --brightness "$BRIGHTNESS" --contrast "$CONTRAST" \
      --saturation "$SATURATION" --sharpness "$SHARPNESS" \
      --denoise "$DENOISE"

    if [ "$HFLIP" = "true" ]; then set -- "$@" --hflip; fi
    if [ "$VFLIP" = "true" ]; then set -- "$@" --vflip; fi

    exec ${rpicamVid} "$@" -o -
  '';

  # Applied by the firmware after a camera config change. Restarts the stream so
  # the wrapper above re-reads the config. `--no-block` keeps the firmware's
  # websocket loop responsive while systemd restarts the unit.
  cameraApply = pkgs.writeShellScriptBin "manafish-camera" ''
    exec ${systemctl} restart --no-block go2rtc.service
  '';
in {
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
    cameraApply
  ];

  # Allow `pi` to restart only go2rtc.service without a password, so camera
  # setting changes can be applied at runtime without a rebuild.
  security.polkit = {
    enable = true;
    extraConfig = ''
      polkit.addRule(function (action, subject) {
        if (
          action.id == "org.freedesktop.systemd1.manage-units" &&
          action.lookup("unit") == "go2rtc.service" &&
          subject.user == "pi"
        ) {
          return polkit.Result.YES;
        }
      });
    '';
  };

  # Run go2rtc as `pi` so the stream wrapper can read the 0600 ROV config file
  # (owner match). The `video` group grants access to the camera devices.
  systemd.services.go2rtc.serviceConfig = {
    DynamicUser = lib.mkForce false;
    User = lib.mkForce "pi";
    Group = lib.mkForce "video";
    ProtectHome = lib.mkForce false;
  };

  services.go2rtc = {
    enable = true;
    settings = {
      # Camera and encoder parameters are generated at launch from the ROV
      # config by manafish-camera-stream, so they can be changed from the app
      # without rebuilding the firmware image.
      streams.cam = "exec:${cameraStream}";
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
