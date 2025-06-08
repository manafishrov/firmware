#include <stdio.h>
#include "pico/stdlib.h"
#include "dshot.h"
#include "hardware/pio.h"
#include <inttypes.h>

#define NUM_THRUSTERS 8
#define DSHOT_SPEED DSHOT_600

const uint THRUSTER_PINS[NUM_THRUSTERS] = {
    10, 11, 12, 13,
    21, 20, 19, 18
};

struct dshot_controller thruster_controllers[NUM_THRUSTERS];

void telemetry_callback(void *context, int controller_channel_idx, enum dshot_telemetry_type type, int value) {
    int thruster_idx = (int)(uintptr_t)context;

    printf("Thruster %d (Pin %2d, PIO%d/SM%d) Telemetry: ",
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

int main() {
    stdio_init_all();
    sleep_ms(3000);

    printf("--------------------------------------\n");
    printf("Manafish Pico DShot Firmware Starting\n");
    printf("--------------------------------------\n");
    printf("Initializing %d thrusters with DSHOT%d...\n", NUM_THRUSTERS, DSHOT_SPEED);

    for (int i = 0; i < NUM_THRUSTERS; ++i) {
        PIO pio_instance = (i < 4) ? pio0 : pio1;
        uint8_t sm_instance = (i < 4) ? i : (i - 4);

        dshot_controller_init(&thruster_controllers[i], DSHOT_SPEED, pio_instance, sm_instance, THRUSTER_PINS[i], 1);
        dshot_register_telemetry_cb(&thruster_controllers[i], telemetry_callback, (void*)(uintptr_t)i);

        printf("  Thruster %d: PIO%d, SM%d, Pin GP%d initialized.\n",
               i, pio_get_index(pio_instance), sm_instance, THRUSTER_PINS[i]);
    }
    printf("All thrusters initialized.\n");

    printf("Arming ESCs (sending 0 throttle for 1 second)...\n");
    absolute_time_t arming_end_time = make_timeout_time_ms(1000);
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
    printf("Arming sequence complete.\n\n");

    uint16_t forward_throttle_value = 60;
    uint16_t reverse_throttle_value = 1060;

    while (true) {
        for (int i = 0; i < NUM_THRUSTERS; ++i) {
            printf("\n--- Testing Thruster %d (Pin GP%d) ---\n", i, THRUSTER_PINS[i]);

            printf("Thruster %d: Enabling extended telemetry...\n", i);
            for (int k = 0; k < 15; ++k) {
                dshot_command(&thruster_controllers[i], 0, DSHOT_CMD_EXTENDED_TELEMETRY_ENABLE);
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }
            printf("Thruster %d: Spinning FORWARD (throttle %u)...\n", i, forward_throttle_value);
            dshot_throttle(&thruster_controllers[i], 0, forward_throttle_value);
            for (int k = 0; k < 100; ++k) {
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }

            printf("Thruster %d: Spinning REVERSE (throttle %u)...\n", i, reverse_throttle_value);
            dshot_throttle(&thruster_controllers[i], 0, reverse_throttle_value);
            for (int k = 0; k < 100; ++k) {
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }

            printf("Thruster %d: Stopping (throttle 0)...\n", i);
            dshot_throttle(&thruster_controllers[i], 0, 0);
            for (int k = 0; k < 50; ++k) {
                dshot_loop(&thruster_controllers[i]);
                sleep_ms(10);
            }
            printf("--- Thruster %d test complete. ---\n", i);
            sleep_ms(1000);
        }
        printf("\nAll thrusters cycled. Repeating sequence in 5 seconds...\n");
        sleep_ms(5000);
    }

    return 0;
}
