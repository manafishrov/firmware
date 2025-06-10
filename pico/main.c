#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "pico/time.h"
#include "dshot.h"

#define MOTOR_PIN 10

#define DSHOT_PIO pio0
#define DSHOT_SM 0
#define DSHOT_SPEED 600

#define DSHOT_THROTTLE_NEUTRAL 1048
#define DSHOT_THROTTLE_MAX_FORWARD 2047
#define DSHOT_THROTTLE_MAX_REVERSE 48

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

void telemetry_callback(
    void *context,
    int channel,
    enum dshot_telemetry_type type,
    int value
) {
}

int main() {
    stdio_init_all();
    sleep_ms(4000);

    printf("Pico DShot ROV Ramping Test\n");
    printf("----------------------------------\n");
    printf(
        "Power on ESC now. Arming with neutral signal for %d seconds...\n",
        ARMING_DURATION_S
    );

    struct dshot_controller controller;
    dshot_controller_init(
        &controller,
        DSHOT_SPEED,
        DSHOT_PIO,
        DSHOT_SM,
        MOTOR_PIN,
        1
    );
    dshot_register_telemetry_cb(&controller, telemetry_callback, NULL);

    enum test_state current_state = STATE_ARMING;
    uint64_t state_start_time = time_us_64();
    uint64_t current_state_duration = (uint64_t)ARMING_DURATION_S * 1000000;
    uint16_t current_throttle = DSHOT_THROTTLE_NEUTRAL;

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
        case STATE_PAUSE_1:
        case STATE_DONE:
            current_throttle = DSHOT_THROTTLE_NEUTRAL;
            break;
        case STATE_RAMP_FORWARD_UP:
            current_throttle = DSHOT_THROTTLE_NEUTRAL + (uint16_t)(100 * progress);
            break;
        case STATE_RAMP_FORWARD_DOWN:
            current_throttle = (DSHOT_THROTTLE_NEUTRAL + 100) - (uint16_t)(100 * progress);
            break;
        case STATE_RAMP_REVERSE_UP:
            current_throttle = (48) + (uint16_t)(100 * progress);
            break;
        case STATE_RAMP_REVERSE_DOWN:
            current_throttle = 148 - (uint16_t)(100 * progress);
            break;
        }
        dshot_throttle(&controller, 0, current_throttle);
        dshot_loop(&controller);
    }

    return 0;
}
