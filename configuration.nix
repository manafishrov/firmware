{ config, pkgs, lib, ... }:
{
  system.stateVersion = "25.05";
  networking = {
    hostName = "cyberfish";
    # This is the IP of the computer connecting to the Pi (I will try this later to avoid wifi all together)
    # defaultGateway = "10.10.10.11";
    # nameservers = [ "10.10.10.11" ];
    interfaces.eth0 = {
      useDHCP = false;
      ipv4.addresses = [{
        # This is the static IP of the Pi used for connecting to it
        address = "10.10.10.10";
        prefixLength = 24;
      }];
    };
  };

  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = true;
      PermitRootLogin = "yes";
    };
  };

  users.users.op = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
    password = "cyberfish";
  };

  environment.systemPackages = with pkgs; [
    nvim
    nano
    python3
  ];

  hardware.enableRedistributableFirmware = true;
  boot.kernelPackages = pkgs.linuxPackages;
}
