#ifndef PWM_H
#define PWM_H

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pwm.h"
#include <stdint.h>

#define PWM_MAX_CHANNELS 8
#define PWM_FREQUENCY 50
<<<<<<< HEAD
#define PWM_FULL_REVERSE 1000
#define PWM_NEUTRAL 1500
#define PWM_FULL_FORWARD 2000 // The different levels for PWM signals in microseconds
=======
>>>>>>> 76a0a1fca9108cd982acd551b610e49e7f322a67

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
