{
  pkgs,
  lib,
  ...
}: let
  jq = lib.getExe pkgs.jq;
  nmcli = lib.getExe' pkgs.networkmanager "nmcli";
  python = lib.getExe pkgs.python3;
  systemctl = lib.getExe' pkgs.systemd "systemctl";
  dnsmasqConfig = "/run/manafish/dnsmasq.conf";

  networkScript = pkgs.writeShellScriptBin "manafish-network" ''
    set -euo pipefail

    CONFIG="/home/pi/firmware/src/rov_firmware/config.json"
    DEFAULT_IP="10.10.10.10"
    PREFIX="24"
    CONNECTION="eth0"
    DNSMASQ_CONFIG="${dnsmasqConfig}"

    if [ -f "$CONFIG" ]; then
      IP=$(${jq} -r '.ipAddress // empty' "$CONFIG" 2>/dev/null)
    fi
    IP="''${IP:-$DEFAULT_IP}"

    ${python} - "$IP" "$DNSMASQ_CONFIG" <<'PY'
    from ipaddress import IPv4Address, IPv4Network
    from pathlib import Path
    import sys

    address = IPv4Address(sys.argv[1])
    network = IPv4Network(f"{address}/24", strict=False)
    if address in (network.network_address, network.broadcast_address):
        raise ValueError(f"{address} is not a usable /24 host address")

    host = int(address) - int(network.network_address)
    start_host, end_host = (50, 100) if 150 <= host <= 200 else (150, 200)
    start = IPv4Address(int(network.network_address) + start_host)
    end = IPv4Address(int(network.network_address) + end_host)

    Path(sys.argv[2]).write_text(
        f"dhcp-range={start},{end},255.255.255.0,12h\n",
        encoding="utf-8",
    )
    PY

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
    ${systemctl} restart --no-block dnsmasq.service

    # At runtime the firmware server is still bound to the previous address.
    # Restart it so it binds the new address; at boot try-restart is a no-op
    # and the normal service ordering starts it later.
    ${systemctl} try-restart --no-block manafish-firmware.service
  '';
in {
  # Keep the onboard radios powered down; the ROV communicates over Ethernet.
  hardware.raspberry-pi.config.all.dt-overlays = {
    disable-wifi = {
      enable = true;
      params = {};
    };
    disable-bt = {
      enable = true;
      params = {};
    };
  };

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

  # The network helper is run by root during boot and by `pi` after a runtime
  # config change. Give both paths one transient location for the subnet-aware
  # dnsmasq configuration.
  systemd.tmpfiles.rules = ["d /run/manafish 0755 pi users -"];

  # Applying a new ROV address must reload the matching DHCP pool and rebind
  # the firmware server. Limit the firmware user to those two units.
  security.polkit = {
    enable = true;
    extraConfig = ''
      polkit.addRule(function (action, subject) {
        if (
          action.id == "org.freedesktop.systemd1.manage-units" &&
          ["dnsmasq.service", "manafish-firmware.service"].indexOf(
            action.lookup("unit")
          ) >= 0 &&
          subject.user == "pi"
        ) {
          return polkit.Result.YES;
        }
      });
    '';
  };

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
      resolveLocalQueries = false;
      settings = {
        interface = "eth0";
        bind-dynamic = true;
        port = 0;
        dhcp-authoritative = true;
        conf-file = dnsmasqConfig;

        # Android identifies its DHCP client with an android-dhcp-* vendor
        # class. It requires router and DNS options before treating Ethernet
        # as provisioned, even though this isolated link provides neither
        # service. Other clients receive no default route or DNS server, so a
        # laptop's normal internet connection is not replaced by the tether.
        dhcp-vendorclass = "set:android,android-dhcp-";
        dhcp-option = [
          "option:router"
          "option:dns-server"
          "tag:android,option:router,0.0.0.0"
          "tag:android,option:dns-server,0.0.0.0"
        ];
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

  # The WebSocket config handler runs inside this restricted service.
  systemd.services.manafish-firmware.path = [networkScript];

  systemd.services.dnsmasq = {
    after = ["manafish-network.service"];
    requires = ["manafish-network.service"];
  };
}
