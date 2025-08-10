#ifndef PWM_H
#define PWM_H

#include <stdint.h>
#include "hardware/pwm.h"
#include "hardware/gpio.h"
#include "hardware/clocks.h"

#define PWM_MAX_CHANNELS 8
#define PWM_FREQUENCY 400
#define PWM_RANGE 2000

struct pwm_controller {
    uint slice[PWM_MAX_CHANNELS];
    uint pin[PWM_MAX_CHANNELS];
    uint num_channels;
};

void pwm_controller_init(struct pwm_controller *controller, uint *pins, uint num_channels);

void pwm_set_throttle(struct pwm_controller *controller, uint channel, uint value);

#endif

