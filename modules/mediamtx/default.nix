{ ... }:
{
  services.mediamtx = {
    enable = true;
    allowVideoAccess = true;
    settings = {
      rtsp = "no";
      rtmp = "no";
      hls = "no";
      srt = "no";
      webrtc = "yes";
      webrtcAddress = ":8889";
      paths = {
        source = "rpiCamera";
        sourceType = "yes";
        sourceOnDemandStartTimeout = "1s";
        sourceOnDemandCloseAfter = "1s";
        rpiCameraAfSpeed = "fast";
      };
    };
  };
}
