{pkgs, ...}: {
  # Header interfaces for custom-action peripherals. Each one claims its pins,
  # so they are no longer available as plain GPIO:
  #   I2C1  GPIO2/3      /dev/i2c-1 (1 MHz, shared with the ROV sensors)
  #   1-Wire GPIO4       /sys/bus/w1/devices (external 4.7k pull-up to 3V3)
  #   SPI0  GPIO7-11     /dev/spidev0.0 (CE0 GPIO8), /dev/spidev0.1 (CE1 GPIO7)
  #   PWM   GPIO18/19    /sys/class/pwm/pwmchip0 channels 0/1
  hardware = {
    i2c.enable = true;
    raspberry-pi.config.all = {
      base-dt-params = {
        i2c_arm = {
          enable = true;
          value = "on";
        };
        i2c_arm_baudrate = {
          enable = true;
          value = 1000000;
        };
        # SPI0 (/dev/spidev0.*, MOSI on GPIO10), e.g. for WS2812 LED strips.
        spi = {
          enable = true;
          value = "on";
        };
        # The Pi 3 analog audio output uses the PWM block needed below, and the
        # ROV has no use for the headphone jack.
        audio.enable = false;
      };
      dt-overlays = {
        # Hardware PWM on GPIO18 (channel 0) and GPIO19 (channel 1) for servos,
        # LED drivers and ESC-style signals. udev grants the gpio group access.
        pwm-2chan = {
          enable = true;
          params = {};
        };
        # 1-Wire bus on GPIO4, e.g. for DS18B20 temperature probes.
        w1-gpio = {
          enable = true;
          params = {};
        };
      };
      # The Pi 3 SPI and I2C clocks are divided from the VPU core clock, which
      # otherwise drops to 250 MHz when idle. Holding it at its 400 MHz maximum
      # keeps SPI-generated WS2812 timing (and the I2C rate) stable.
      options.core_freq_min = {
        enable = true;
        value = 400;
      };
    };
  };

  # Expose /dev/i2c-* devices for I2C sensors.
  boot.kernelModules = ["i2c-dev"];

  environment.systemPackages = with pkgs; [
    i2c-tools
  ];
}
