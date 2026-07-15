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
    # DHCP server for Android phones/tablets connected through a USB-C
    # ethernet adapter. Android's ethernet stack expects DHCP and often has
    # no static-IP UI, so without this a phone plugged into the tether never
    # gets an address. DHCP only (port = 0 disables DNS entirely), scoped to
    # eth0 so WiFi is never touched. The lease range 10.10.10.150-200
    # excludes the Pi itself (.10) and the documented static PC (.100). No
    # default gateway or DNS servers are pushed (empty dhcp-option 3/6) so
    # phones keep using WiFi for internet. Statically configured PCs are
    # unaffected: they never send a DHCPDISCOVER, and the range exclusion
    # prevents lease collisions.
    # Caveat: like the mDNS/static-IP setup above, the range assumes the
    # default 10.10.10.0/24 subnet. If the operator changes the ROV IP to a
    # different subnet, dnsmasq stops matching eth0 and simply offers no
    # leases; phone clients must then use manual addressing.
    dnsmasq = {
      enable = true;
      # DNS is disabled, so never point the Pi's own resolv.conf at dnsmasq.
      resolveLocalQueries = false;
      settings = {
        interface = "eth0";
        # bind-interfaces (rather than bind-dynamic) is the more robust
        # choice here: with port = 0 there are no DNS sockets that could
        # race with addresses appearing later, and binding strictly to eth0
        # guarantees dnsmasq can never leak onto the WiFi interface. The
        # only startup requirement -- eth0 having its address before dnsmasq
        # binds -- is handled by ordering the unit after
        # manafish-network.service (see systemd.services.dnsmasq below).
        bind-interfaces = true;
        port = 0;
        dhcp-range = "10.10.10.150,10.10.10.200,255.255.255.0,12h";
        # Empty option 3 (router) and 6 (dns-server): push no gateway and
        # no DNS, so Android keeps routing internet traffic over WiFi.
        dhcp-option = ["3" "6"];
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
