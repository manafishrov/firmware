#ifndef PWM_H
#define PWM_H

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pwm.h"
#include <stdint.h>

#define PWM_MAX_CHANNELS 8
#define PWM_FREQUENCY 50
#define PWM_PERIOD_US 20000
#define PWM_STEPS 4096
#define PWM_WRAP (PWM_STEPS - 1)

struct pwm_controller {
  uint slice[PWM_MAX_CHANNELS];
  uint pin[PWM_MAX_CHANNELS];
  uint num_channels;
};

void pwm_controller_init(struct pwm_controller *controller, uint *pins,
                         uint num_channels);

void pwm_set_throttle(struct pwm_controller *controller, uint channel,
                      uint value);

#endif
