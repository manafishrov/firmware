#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pwm.h"
#include "hardware/clocks.h"
#include "pico/time.h"

#define MOTOR_PIN 21

#define PWM_CLOCK_DIVIDER 125.0f
#define PWM_WRAP 20000

#define MIN_PULSE_US 1000
#define NEUTRAL_PULSE_US 1488
#define MAX_PULSE_US 2000

#define ARMING_DURATION_S 12
#define RAMP_DURATION_MS 4000
#define PAUSE_DURATION_MS 2000

enum test_state {
    STATE_ARMING,
    STATE_RAMP_FORWARD_UP,
    STATE_RAMP_FORWARD_DOWN,
    STATE_PAUSE_1,
    STATE_RAMP_REVERSE_UP,
    STATE_RAMP_REVERSE_DOWN,
    STATE_DONE
};

void set_motor_pulse(uint slice_num, uint chan, uint16_t pulse_us) {
    if (pulse_us > PWM_WRAP) {
        pulse_us = PWM_WRAP;
        printf("Warning: Pulse width %u us capped at WRAP value %u us.\n", pulse_us, PWM_WRAP);
    }
    pwm_set_chan_level(slice_num, chan, pulse_us);
}

int main() {
    stdio_init_all();
    sleep_ms(4000);

    printf("Pico PWM ROV Ramping Test\n");
    printf("----------------------------------\n");
    printf("Power on ESC now. Arming with minimum signal for %d seconds...\n", ARMING_DURATION_S);

    gpio_set_function(MOTOR_PIN, GPIO_FUNC_PWM);
    uint slice_num = pwm_gpio_to_slice_num(MOTOR_PIN);
    uint chan = pwm_gpio_to_channel(MOTOR_PIN);

    pwm_config config = pwm_get_default_config();
    pwm_config_set_clkdiv(&config, PWM_CLOCK_DIVIDER);
    pwm_config_set_wrap(&config, PWM_WRAP);
    pwm_init(slice_num, &config, true);

    enum test_state current_state = STATE_ARMING;
    uint64_t state_start_time = time_us_64();
    uint64_t current_state_duration = (uint64_t)ARMING_DURATION_S * 1000000;
    uint16_t current_pulse = MIN_PULSE_US;

    while (true) {
        uint64_t now = time_us_64();
        uint64_t elapsed_in_state = now - state_start_time;

        if (elapsed_in_state >= current_state_duration) {
            state_start_time = now;
            switch (current_state) {
            case STATE_ARMING:
                current_state = STATE_RAMP_FORWARD_UP;
                current_state_duration = RAMP_DURATION_MS * 1000;
                printf("Arming complete. Ramping FORWARD UP...\n");
                break;
            case STATE_RAMP_FORWARD_UP:
                current_state = STATE_RAMP_FORWARD_DOWN;
                current_state_duration = RAMP_DURATION_MS * 1000;
                printf("Ramping FORWARD DOWN...\n");
                break;
            case STATE_RAMP_FORWARD_DOWN:
                current_state = STATE_PAUSE_1;
                current_state_duration = PAUSE_DURATION_MS * 1000;
                printf("Pausing at neutral...\n");
                break;
            case STATE_PAUSE_1:
                current_state = STATE_RAMP_REVERSE_UP;
                current_state_duration = RAMP_DURATION_MS * 1000;
                printf("Ramping REVERSE UP...\n");
                break;
            case STATE_RAMP_REVERSE_UP:
                current_state = STATE_RAMP_REVERSE_DOWN;
                current_state_duration = RAMP_DURATION_MS * 1000;
                printf("Ramping REVERSE DOWN...\n");
                break;
            case STATE_RAMP_REVERSE_DOWN:
                current_state = STATE_DONE;
                current_state_duration = -1;
                printf("Test complete. Idling at neutral.\n");
                break;
            case STATE_DONE:
                break;
            }
            elapsed_in_state = now - state_start_time;
        }

        float progress = (float)elapsed_in_state / (float)current_state_duration;
        if (progress > 1.0f) {
            progress = 1.0f;
        }

        switch (current_state) {
        case STATE_ARMING:
            current_pulse = MIN_PULSE_US;
            break;
        case STATE_PAUSE_1:
        case STATE_DONE:
            current_pulse = NEUTRAL_PULSE_US;
            break;
        case STATE_RAMP_FORWARD_UP:
            current_pulse = NEUTRAL_PULSE_US + (uint16_t)((MAX_PULSE_US - NEUTRAL_PULSE_US) * progress);
            break;
        case STATE_RAMP_FORWARD_DOWN:
            current_pulse = MAX_PULSE_US - (uint16_t)((MAX_PULSE_US - NEUTRAL_PULSE_US) * progress);
            break;
        case STATE_RAMP_REVERSE_UP:
            current_pulse = NEUTRAL_PULSE_US - (uint16_t)((NEUTRAL_PULSE_US - MIN_PULSE_US) * progress);
            break;
        case STATE_RAMP_REVERSE_DOWN:
            current_pulse = MIN_PULSE_US + (uint16_t)((NEUTRAL_PULSE_US - MIN_PULSE_US) * progress);
            break;
        }

        set_motor_pulse(slice_num, chan, current_pulse);
        sleep_ms(1);
    }

    return 0;
}
