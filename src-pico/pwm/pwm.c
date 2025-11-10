#include "pwm.h"
#include <string.h>

void pwm_controller_init(struct pwm_controller *controller, uint *pins, uint num_channels) {
    memset(controller, 0, sizeof(*controller));
    controller->num_channels = num_channels;

    for (uint i = 0; i < num_channels; ++i) {
        controller->pin[i] = pins[i];
        gpio_set_function(pins[i], GPIO_FUNC_PWM);
        controller->slice[i] = pwm_gpio_to_slice_num(pins[i]);

        uint32_t clock = clock_get_hz(clk_sys);
        float divider = clock / (PWM_FREQUENCY * 65535.0f);
        uint32_t wrap = (uint32_t)(clock / (divider * PWM_FREQUENCY));

        pwm_set_clkdiv(controller->slice[i], divider);
        pwm_set_wrap(controller->slice[i], wrap);
        pwm_set_enabled(controller->slice[i], true);
    }
}

void pwm_set_throttle(struct pwm_controller *controller, uint channel, uint value) {
    if (channel >= controller->num_channels) return;

    uint32_t clock = clock_get_hz(clk_sys);
    uint32_t divider = pwm_get_clkdiv(controller->slice[channel]);
    uint32_t wrap = pwm_get_wrap(controller->slice[channel]);

    float pulse_us = PWM_FULL_REVERSE + ((float)value / 2000.0f) * (PWM_FULL_FORWARD - PWM_FULL_REVERSE);
    float period_us = 1e6f / PWM_FREQUENCY;
    uint32_t level = (pulse_us / period_us) * wrap;

    pwm_set_gpio_level(controller->pin[channel], level);
}
