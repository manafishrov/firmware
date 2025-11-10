#include "pwm.h"
#include <string.h>

void pwm_controller_init(struct pwm_controller *controller, uint *pins,
                         uint num_channels) {
  memset(controller, 0, sizeof(*controller));
  controller->num_channels = num_channels;

  for (uint i = 0; i < num_channels; ++i) {
    controller->pin[i] = pins[i];
    gpio_set_function(pins[i], GPIO_FUNC_PWM);

    uint slice = pwm_gpio_to_slice_num(pins[i]);
    controller->slice[i] = slice;

    uint32_t clock = clock_get_hz(clk_sys);
    uint32_t divider = clock / (PWM_FREQUENCY * PWM_STEPS);

    pwm_set_clkdiv(slice, (float)divider);
    pwm_set_wrap(slice, PWM_WRAP);
    pwm_set_enabled(slice, true);
  }
}

void pwm_set_throttle(struct pwm_controller *controller, uint channel,
                      uint value) {
  if (channel >= controller->num_channels) {
    return;
  }

  if (value > PWM_WRAP) {
    value = PWM_WRAP;
  }

  pwm_set_gpio_level(controller->pin[channel], value);
}
