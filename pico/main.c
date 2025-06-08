#include <stdio.h>
#include "pico/stdlib.h"
#include "dshot.h"
#include "hardware/pio.h"
#include "hardware/pwm.h"

#define NUM_THRUSTERS 8
#define DSHOT_SPEED DSHOT_150

const uint THRUSTER_PINS[NUM_THRUSTERS] = {
    10, 11, 12, 13,
    21, 20, 19, 18
};

struct dshot_controller thruster_controllers[NUM_THRUSTERS];

void telemetry_callback(void *context, int controller_channel_idx, enum dshot_telemetry_type type, int value) {
    int thruster_idx = (int)(uintptr_t)context;

    printf("Thruster %d (Pin %2d, PIO%d/SM%d) DShot Telemetry: ",
           thruster_idx,
           thruster_controllers[thruster_idx].pin,
           pio_get_index(thruster_controllers[thruster_idx].pio),
           thruster_controllers[thruster_idx].sm);

    switch (type) {
        case DSHOT_TELEMETRY_ERPM:
            printf("ERPM = %d\n", value);
            break;
        case DSHOT_TELEMETRY_VOLTAGE:
            printf("Voltage = %d (ESC specific units, e.g. V or 10mV)\n", value);
            break;
        case DSHOT_TELEMETRY_CURRENT:
            printf("Current = %d (ESC specific units, e.g. A or 100mA)\n", value);
            break;
        case DSHOT_TELEMETRY_TEMPERATURE:
            printf("Temperature = %d C\n", value);
            break;
        default:
            printf("Unknown type %d, value %d\n", type, value);
            break;
    }
}

#define PWM_ZERO_THROTTLE_US 1488
#define PWM_FORWARD_TEST_US (PWM_ZERO_THROTTLE_US + 200)
#define PWM_REVERSE_TEST_US (PWM_ZERO_THROTTLE_US - 200)

#define PWM_CLOCK_DIV 125.0f
#define PWM_WRAP_VALUE 20000

void pwm_init_pin(uint pin, uint16_t initial_pulse_us) {
    gpio_set_function(pin, GPIO_FUNC_PWM);
    uint slice_num = pwm_gpio_to_slice_num(pin);

    pwm_config config = pwm_get_default_config();
    pwm_config_set_clkdiv(&config, PWM_CLOCK_DIV);
    pwm_config_set_wrap(&config, PWM_WRAP_VALUE);
    pwm_init(slice_num, &config, true);

    pwm_set_gpio_level(pin, initial_pulse_us);
}

void pwm_set_throttle_us(uint pin, uint16_t pulse_us) {
    uint16_t clamped_pulse_us = pulse_us;
    if (clamped_pulse_us < 1000) clamped_pulse_us = 1000;
    if (clamped_pulse_us > 2000) clamped_pulse_us = 2000;
    pwm_set_gpio_level(pin, clamped_pulse_us);
}


int main() {
    stdio_init_all();
    sleep_ms(7000);

    printf("--------------------------------------\n");
    printf("Manafish Pico DShot & PWM Firmware Starting\n");
    printf("--------------------------------------\n");
    printf("Initializing %d thrusters for DSHOT%d...\n", NUM_THRUSTERS, DSHOT_SPEED);

    for (int i = 0; i < NUM_THRUSTERS; ++i) {
        PIO pio_instance = (i < 4) ? pio0 : pio1;
        uint8_t sm_instance = (i < 4) ? i : (i - 4);

        dshot_controller_init(&thruster_controllers[i], DSHOT_SPEED, pio_instance, sm_instance, THRUSTER_PINS[i], 1);
        dshot_register_telemetry_cb(&thruster_controllers[i], telemetry_callback, (void*)(uintptr_t)i);

        printf("  Thruster %d: DShot on PIO%d, SM%d, Pin GP%d initialized.\n",
               i, pio_get_index(pio_instance), sm_instance, THRUSTER_PINS[i]);
    }
    printf("All thrusters DShot initialized.\n");

    printf("Arming ESCs with DShot (sending 0 throttle for 3 seconds)...\n");
    absolute_time_t arming_end_time = make_timeout_time_ms(3000);
    while (absolute_time_diff_us(get_absolute_time(), arming_end_time) > 0) {
        for (int i = 0; i < NUM_THRUSTERS; ++i) {
            dshot_throttle(&thruster_controllers[i], 0, 0);
            dshot_loop_async_start(&thruster_controllers[i]);
        }
        for (int i = 0; i < NUM_THRUSTERS; ++i) {
            dshot_loop_async_complete(&thruster_controllers[i]);
        }
        sleep_ms(5);
    }
    printf("DShot Arming sequence complete.\n\n");
    sleep_ms(15000);

    uint16_t dshot_forward_throttle_value = 500;
    uint16_t dshot_reverse_throttle_value = 1500;

    while (true) {
        printf("\n\n======================================\n");
        printf("=== STARTING DSHOT TEST CYCLE ===\n");
        printf("======================================\n");

        printf("Configuring pins for DShot and enabling PIO State Machines...\n");
        for (int i = 0; i < NUM_THRUSTERS; ++i) {
            uint slice_num = pwm_gpio_to_slice_num(THRUSTER_PINS[i]);
            pwm_set_enabled(slice_num, false);

            pio_gpio_init(thruster_controllers[i].pio, THRUSTER_PINS[i]);
            pio_sm_set_enabled(thruster_controllers[i].pio, thruster_controllers[i].sm, true);
        }
        printf("Pins configured for DShot.\n");
        sleep_ms(100);


        for (int i = 0; i < NUM_THRUSTERS; ++i) {
            printf("\n--- Testing Thruster %d (Pin GP%d) with DSHOT ---\n", i, THRUSTER_PINS[i]);

            printf("Thruster %d: Enabling extended telemetry (sending command 15 times)...\n", i);
            for (int k = 0; k < 15; ++k) {
                dshot_command(&thruster_controllers[i], 0, DSHOT_CMD_EXTENDED_TELEMETRY_ENABLE);
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }

            printf("Thruster %d: Spinning FORWARD (DShot throttle %u)...\n", i, dshot_forward_throttle_value);
            dshot_throttle(&thruster_controllers[i], 1, dshot_forward_throttle_value);
            for (int k = 0; k < 100; ++k) {
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }

            printf("Thruster %d: Spinning REVERSE (DShot throttle %u)...\n", i, dshot_reverse_throttle_value);
            dshot_throttle(&thruster_controllers[i], 1, dshot_reverse_throttle_value);
            for (int k = 0; k < 100; ++k) {
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }

            printf("Thruster %d: Stopping (DShot throttle 0)...\n", i);
            dshot_throttle(&thruster_controllers[i], 1, 0);
            for (int k = 0; k < 50; ++k) {
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }
            printf("--- Thruster %d DSHOT test complete. ---\n", i);
            sleep_ms(15000);
        }
        printf("\n=== DSHOT TEST CYCLE COMPLETE ===\n");
        sleep_ms(2000);

        printf("\n\n======================================\n");
        printf("=== STARTING PWM TEST CYCLE ===\n");
        printf("======================================\n");
        printf("Initializing PWM for thrusters (0 pulse: %d us)...\n", PWM_ZERO_THROTTLE_US);
        for (int i = 0; i < NUM_THRUSTERS; ++i) {
            pio_sm_set_enabled(thruster_controllers[i].pio, thruster_controllers[i].sm, false);
            pwm_init_pin(THRUSTER_PINS[i], PWM_ZERO_THROTTLE_US);
            printf("  Thruster %d (Pin GP%d): PWM initialized.\n", i, THRUSTER_PINS[i]);
        }

        printf("Arming ESCs for PWM (sending %d us for 3 seconds)...\n", PWM_ZERO_THROTTLE_US);
        absolute_time_t pwm_arming_end_time = make_timeout_time_ms(3000);
        while (absolute_time_diff_us(get_absolute_time(), pwm_arming_end_time) > 0) {
            sleep_ms(20);
        }
        printf("PWM Arming sequence complete.\n\n");
        sleep_ms(15000);

        for (int i = 0; i < NUM_THRUSTERS; ++i) {
            printf("\n--- Testing Thruster %d (Pin GP%d) with PWM ---\n", i, THRUSTER_PINS[i]);

            printf("Thruster %d: Spinning FORWARD (PWM %u us)...\n", i, PWM_FORWARD_TEST_US);
            pwm_set_throttle_us(THRUSTER_PINS[i], PWM_FORWARD_TEST_US);
            sleep_ms(2000);

            printf("Thruster %d: Spinning REVERSE (PWM %u us)...\n", i, PWM_REVERSE_TEST_US);
            pwm_set_throttle_us(THRUSTER_PINS[i], PWM_REVERSE_TEST_US);
            sleep_ms(2000);

            printf("Thruster %d: Stopping (PWM %u us)...\n", i, PWM_ZERO_THROTTLE_US);
            pwm_set_throttle_us(THRUSTER_PINS[i], PWM_ZERO_THROTTLE_US);
            sleep_ms(1000);

            printf("--- Thruster %d PWM test complete. ---\n", i);
            sleep_ms(15000);
        }
        printf("\n=== PWM TEST CYCLE COMPLETE ===\n");

        printf("\nAll thrusters cycled (DShot & PWM). Repeating sequence in 3 seconds...\n");
        sleep_ms(3000);
    }

    return 0;
}
