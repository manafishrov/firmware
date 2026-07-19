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
    usePredictableInterfaceNames = false;
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
    dnsmasq = {
      enable = true;
      # DNS is disabled; don't point the Pi's own resolv.conf at dnsmasq.
      resolveLocalQueries = false;
      settings = {
        interface = "eth0";
        # bind-dynamic (not bind-interfaces) so dnsmasq re-binds when eth0's
        # address comes and goes, e.g. when the tether cable is unplugged.
        bind-dynamic = true;
        port = 0;
        dhcp-range = "10.10.10.150,10.10.10.200,255.255.255.0,12h";
        # Android only accepts a DHCP lease once IPv4 is considered
        # "provisioned", which requires a router (opt 3) and DNS server
        # (opt 6) to be present, even though neither is actually used here:
        # DNS stays off (port = 0) and the Pi doesn't forward, so WiFi
        # remains the default network for internet access.
        dhcp-option = ["3,10.10.10.10" "6,10.10.10.10"];
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

  # Make sure eth0 already carries its static address before dnsmasq starts,
  # so bind-interfaces has an address/subnet to bind the DHCP service to.
  systemd.services.dnsmasq = {
    after = ["manafish-network.service"];
    wants = ["manafish-network.service"];
  };
}
