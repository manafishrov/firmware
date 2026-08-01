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
          value=$4
          ;;
        *) value=$1 ;;
      esac
      [ "$value" -lt "$2" ] && value=$2
      [ "$value" -gt "$3" ] && value=$3
      printf '%s' "$value"
    }

    # clamp_num VALUE MIN MAX DEFAULT -> decimal within [MIN, MAX]. jq handles
    # syntax and bounds together so a corrupt-but-valid JSON config cannot pass
    # malformed values such as "1.2.3" or unsafe values to rpicam-vid.
    clamp_num() {
      ${jq} -nr \
        --arg value "$1" \
        --argjson low "$2" \
        --argjson high "$3" \
        --argjson fallback "$4" \
        '($value | tonumber? // $fallback) as $parsed
        | if $parsed < $low then $low
          elif $parsed > $high then $high
          else $parsed
          end'
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

    # The Pi 3 hardware H.264 encoder is limited to a 1920x1080 output frame.
    WIDTH=$(clamp_int "$(get .camera.width)" 160 1920 1440)
    HEIGHT=$(clamp_int "$(get .camera.height)" 160 1080 1080)
    # H.264 and the camera scaler require complete chroma pairs. The Python
    # model already enforces this, but repeat it here for manually edited or
    # otherwise corrupted persisted configuration.
    WIDTH=$(( WIDTH - WIDTH % 2 ))
    HEIGHT=$(( HEIGHT - HEIGHT % 2 ))
    CROP_FOV=$(get .camera.cropFov)

    # Repeat the firmware model's resolution-aware limit here because go2rtc
    # starts without trusting the persisted JSON. This combines the selected
    # sensor mode ceiling with H.264 level 4's 245,760 macroblocks/second.
    SENSOR_MAX_FRAMERATE=40
    if [ "$CROP_FOV" = "true" ] && [ "$WIDTH" -le 1332 ] && [ "$HEIGHT" -le 990 ]; then
      SENSOR_MAX_FRAMERATE=120
    fi
    MACROBLOCKS_PER_FRAME=$(( ((WIDTH + 15) / 16) * ((HEIGHT + 15) / 16) ))
    ENCODER_MAX_FRAMERATE=$(( 245760 / MACROBLOCKS_PER_FRAME ))
    MAX_FRAMERATE=$SENSOR_MAX_FRAMERATE
    if [ "$ENCODER_MAX_FRAMERATE" -lt "$MAX_FRAMERATE" ]; then
      MAX_FRAMERATE=$ENCODER_MAX_FRAMERATE
    fi
    FRAMERATE=$(clamp_int "$(get .camera.framerate)" 1 "$MAX_FRAMERATE" 40)
    BITRATE=$(clamp_int "$(get .camera.bitrate)" 1000000 25000000 20000000)
    KEYFRAME_INTERVAL=$(clamp_int "$(get .camera.keyframeInterval)" 1 300 30)
    ROTATION=$(enum_or "$(get .camera.rotation)" 0 0 180)
    PROFILE=$(enum_or "$(get .camera.profile)" baseline baseline main high)
    LEVEL=$(enum_or "$(get .camera.level)" 4.2 4 4.1 4.2)
    AWB=$(enum_or "$(get .camera.awb)" auto \
      auto incandescent tungsten fluorescent indoor daylight cloudy)
    DENOISE=$(enum_or "$(get .camera.denoise)" off \
      auto off cdn_off cdn_fast cdn_hq)
    EV=$(clamp_num "$(get .camera.exposureValue)" -8 8 0)
    BRIGHTNESS=$(clamp_num "$(get .camera.brightness)" -1 1 0)
    CONTRAST=$(clamp_num "$(get .camera.contrast)" 0 15 1)
    SATURATION=$(clamp_num "$(get .camera.saturation)" 0 15 1)
    SHARPNESS=$(clamp_num "$(get .camera.sharpness)" 0 15 1)
    HFLIP=$(get .camera.hflip)
    VFLIP=$(get .camera.vflip)

    # Full-FOV mode (2028x1520, SRGGB12) reads the whole sensor and scales
    # down to WIDTHxHEIGHT; the crop mode (1332x990, SRGGB10) instead reads a
    # ~2/3 crop of the sensor for a higher framerate ceiling. The crop mode is
    # only used when it's actually big enough to produce WIDTHxHEIGHT.
    if [ "$CROP_FOV" = "true" ] && [ "$WIDTH" -le 1332 ] && [ "$HEIGHT" -le 990 ]; then
      MODE="1332:990:10:P"
    else
      MODE="2028:1520:12:P"
    fi

    set -- \
      -t 0 -n --inline \
      --mode "$MODE" \
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
  systemd.services.go2rtc = {
    # The setup unit restores the persisted config while deploying a new image.
    # Do not construct the camera command until that file is in place.
    after = ["manafish-setup.service"];
    requires = ["manafish-setup.service"];
    serviceConfig = {
      DynamicUser = lib.mkForce false;
      User = lib.mkForce "pi";
      Group = lib.mkForce "video";
      ProtectHome = lib.mkForce false;
    };
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
