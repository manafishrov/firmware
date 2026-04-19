_: {
  networking = {
    hostName = "manafish";
    interfaces.eth0.ipv4.addresses = [
      {
        address = "10.10.10.10";
        prefixLength = 24;
      }
    ];
    firewall.enable = false;
    nftables.enable = false;
    wireless.iwd.enable = true;
    networkmanager = {
      enable = true;
      wifi.backend = "iwd";
    };
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
    openssh = {
      enable = true;
      settings.PasswordAuthentication = true;
    };
  };
}
