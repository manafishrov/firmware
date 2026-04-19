{pkgs, ...}: {
  hardware = {
    i2c.enable = true;
    raspberry-pi.config.all.base-dt-params = {
      i2c_arm = {
        enable = true;
        value = "on";
      };
      i2c_arm_baudrate = {
        enable = true;
        value = 1000000;
      };
    };
  };

  environment.systemPackages = with pkgs; [
    i2c-tools
  ];
}
