#include "pwm.h"
#include <string.h>

void pwm_controller_init(struct pwm_controller *controller, uint *pins,
                         uint num_channels) {
  memset(controller, 0, sizeof(*controller));
  controller->num_channels = num_channels;
  for (uint i = 0; i < num_channels; ++i) {
    controller->pin[i] = pins[i];
    gpio_set_function(pins[i], GPIO_FUNC_PWM);
    controller->slice[i] = pwm_gpio_to_slice_num(pins[i]);
    uint32_t clock = clock_get_hz(clk_sys);
    uint32_t divider = clock / (PWM_FREQUENCY * 4096);
    pwm_set_clkdiv(controller->slice[i], divider);
    pwm_set_wrap(controller->slice[i], 4095);
    pwm_set_enabled(controller->slice[i], true);
  }
}

void pwm_set_throttle(struct pwm_controller *controller, uint channel,
                      uint value) {
  if (channel >= controller->num_channels)
    return;
  uint pulse = value * 4096 / 20000;
  if (pulse > 4095)
    pulse = 4095;
  pwm_set_gpio_level(controller->pin[channel], pulse);
}
