#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pwm.h"
#include "hardware/clocks.h"
#include "pico/time.h"

#define MOTOR_PIN 10

#define PWM_CLOCK_DIVIDER 125.0f
#define PWM_WRAP 20000

#define MIN_PULSE_US 1000
#define NEUTRAL_PULSE_US 1488
#define MAX_PULSE_US 2000
#define TEST_SPIN_PULSE_US 1550
#define TEST_SPIN_REVERSE_PULSE_US 1400

#define INITIAL_SERIAL_WAIT_MS 2000
#define STARTUP_DELAY_MS 10000
#define ARMING_DURATION_MS 5000
#define POST_NEUTRAL_DELAY_MS 7000
#define TEST_SPIN_DURATION_MS 3000
#define POST_SPIN_DELAY_MS 2000

void set_motor_pulse(uint slice_num, uint chan, uint16_t pulse_us) {
    if (pulse_us > PWM_WRAP) {
        pulse_us = PWM_WRAP;
        printf("Warning: Pulse width %u us capped at WRAP value %u us.\n", pulse_us, PWM_WRAP);
    }
    pwm_set_chan_level(slice_num, chan, pulse_us);
    printf("Set motor pulse to: %u us\n", pulse_us);
}

int main() {
    stdio_init_all();
    sleep_ms(INITIAL_SERIAL_WAIT_MS);

    printf("Pico PWM Motor Control Firmware\n");
    printf("---------------------------------\n");
    printf("System clock: %lu Hz\n", clock_get_hz(clk_sys));
    printf("MOTOR_PIN: GPIO %d\n", MOTOR_PIN);

    printf("Main logic will start in %d seconds...\n", STARTUP_DELAY_MS / 1000);
    sleep_ms(STARTUP_DELAY_MS);
    printf("Startup delay complete. Initializing motor control.\n");

    printf("Configuring PWM for GPIO %d...\n", MOTOR_PIN);
    gpio_set_function(MOTOR_PIN, GPIO_FUNC_PWM);
    uint slice_num = pwm_gpio_to_slice_num(MOTOR_PIN);
    uint chan = pwm_gpio_to_channel(MOTOR_PIN);
    printf("PWM Slice: %u, Channel: %u\n", slice_num, chan);

    pwm_config config = pwm_get_default_config();
    pwm_config_set_clkdiv(&config, PWM_CLOCK_DIVIDER);
    pwm_config_set_wrap(&config, PWM_WRAP);
    pwm_init(slice_num, &config, false);
    printf("PWM configured: Divider=%.1f, Wrap=%u (for 50Hz with 1us resolution)\n",
           PWM_CLOCK_DIVIDER, PWM_WRAP);

    printf("Starting ESC arming sequence...\n");
    printf("Sending MIN_PULSE (%u us) for %d ms.\n", MIN_PULSE_US, ARMING_DURATION_MS);
    pwm_set_chan_level(slice_num, chan, MIN_PULSE_US);
    pwm_set_enabled(slice_num, true);
    sleep_ms(ARMING_DURATION_MS);
    printf("Arming sequence complete.\n");

    printf("Setting motor to NEUTRAL_PULSE (%u us).\n", NEUTRAL_PULSE_US);
    set_motor_pulse(slice_num, chan, NEUTRAL_PULSE_US);
    printf("Motor at neutral. Waiting %d ms before test spin.\n", POST_NEUTRAL_DELAY_MS);
    sleep_ms(POST_NEUTRAL_DELAY_MS);

    printf("Starting test spin FORWARD...\n");
    printf("Setting motor to TEST_SPIN_PULSE_US (%u us) for %d ms.\n", TEST_SPIN_PULSE_US, TEST_SPIN_DURATION_MS);
    set_motor_pulse(slice_num, chan, TEST_SPIN_PULSE_US);
    sleep_ms(TEST_SPIN_DURATION_MS);
    printf("Test spin forward complete.\n");

    printf("Returning motor to NEUTRAL_PULSE (%u us).\n", NEUTRAL_PULSE_US);
    set_motor_pulse(slice_num, chan, NEUTRAL_PULSE_US);
    printf("Motor at neutral. Waiting %d ms before reverse test spin.\n", POST_SPIN_DELAY_MS);
    sleep_ms(POST_SPIN_DELAY_MS);

    printf("Starting test spin REVERSE...\n");
    printf("Setting motor to TEST_SPIN_REVERSE_PULSE_US (%u us) for %d ms.\n", TEST_SPIN_REVERSE_PULSE_US, TEST_SPIN_DURATION_MS);
    set_motor_pulse(slice_num, chan, TEST_SPIN_REVERSE_PULSE_US);
    sleep_ms(TEST_SPIN_DURATION_MS);
    printf("Test spin reverse complete.\n");

    printf("Returning motor to NEUTRAL_PULSE (%u us).\n", NEUTRAL_PULSE_US);
    set_motor_pulse(slice_num, chan, NEUTRAL_PULSE_US);

    printf("Firmware test sequence complete. Motor at neutral. Listening for commands (not implemented).\n");

    while (true) {
        tight_loop_contents();
    }

    return 0;
}
