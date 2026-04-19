{
  pkgs,
  lib,
  ...
}: let
  jq = lib.getExe pkgs.jq;
  nmcli = lib.getExe' pkgs.networkmanager "nmcli";

  networkScript = pkgs.writeShellScriptBin "manafish-network" ''
    CONFIG="/home/pi/firmware/src/rov_firmware/config.json"
    DEFAULT_IP="10.10.10.10"
    PREFIX="24"
    CONNECTION="eth0"

    if [ -f "$CONFIG" ]; then
      IP=$(${jq} -r '.ipAddress // empty' "$CONFIG" 2>/dev/null)
    fi
    IP="''${IP:-$DEFAULT_IP}"

    if ${nmcli} connection show "$CONNECTION" &>/dev/null; then
      ${nmcli} connection modify "$CONNECTION" \
        ipv4.addresses "$IP/$PREFIX" \
        ipv4.method manual
    else
      ${nmcli} connection add \
        con-name "$CONNECTION" \
        type ethernet \
        ifname eth0 \
        ipv4.addresses "$IP/$PREFIX" \
        ipv4.method manual \
        ipv6.method disabled \
        connection.autoconnect yes
    fi

    ${nmcli} connection up "$CONNECTION"
  '';
in {
  networking = {
    hostName = "manafish";
    firewall.enable = false;
    nftables.enable = false;
    wireless.iwd.enable = true;
    networkmanager = {
      enable = true;
      wifi.backend = "iwd";
    };
  };

  environment.systemPackages = [networkScript];

  services = {
    avahi = {
      enable = true;
      nssmdns4 = true;
      allowInterfaces = ["eth0"];
      publish = {
        enable = true;
        addresses = true;
      };
    };
    openssh = {
      enable = true;
      settings.PasswordAuthentication = true;
    };
  };

  systemd.services.manafish-network = {
    after = ["NetworkManager.service"];
    wants = ["NetworkManager.service"];
    wantedBy = ["multi-user.target"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = lib.getExe networkScript;
    };
  };
}
