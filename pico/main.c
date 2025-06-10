#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "pico/time.h"
#include "dshot.h"

#define MOTOR_PIN_BASE 18
#define NUM_MOTORS 4

#define DSHOT_PIO pio0
#define DSHOT_SM 0
#define DSHOT_SPEED 600

#define DSHOT_THROTTLE_NEUTRAL 1048
#define DSHOT_THROTTLE_MAX_FORWARD 2047
#define DSHOT_THROTTLE_MAX_REVERSE 48

#define ARMING_DURATION_S 12
#define RAMP_DURATION_MS 2000
#define PAUSE_DURATION_MS 1000

enum test_state {
    STATE_ARMING,
    STATE_MOTOR_TEST,
    STATE_DONE
};

enum motor_test_phase {
    PHASE_RAMP_FORWARD_UP,
    PHASE_RAMP_FORWARD_DOWN,
    PHASE_PAUSE_1,
    PHASE_RAMP_REVERSE_UP,
    PHASE_RAMP_REVERSE_DOWN,
    PHASE_PAUSE_2
};

void telemetry_callback(
    void *context,
    int channel,
    enum dshot_telemetry_type type,
    int value
) {
    printf("Channel %d, Type %d, Value %d\n", channel, type, value);
}

int main() {
    stdio_init_all();
    sleep_ms(4000);

    printf("Pico DShot ROV Individual Motor Test\n");
    printf("------------------------------------\n");
    printf("Testing thrusters on pins 18, 19, 20, 21 individually\n");
    printf(
        "Power on ESCs now. Arming with neutral signal for %d seconds...\n",
        ARMING_DURATION_S
    );

    struct dshot_controller controller;
    dshot_controller_init(
        &controller,
        DSHOT_SPEED,
        DSHOT_PIO,
        DSHOT_SM,
        MOTOR_PIN_BASE,
        NUM_MOTORS
    );
    dshot_register_telemetry_cb(&controller, telemetry_callback, NULL);

    enum test_state current_state = STATE_ARMING;
    enum motor_test_phase current_phase = PHASE_RAMP_FORWARD_UP;
    uint64_t state_start_time = time_us_64();
    uint64_t current_state_duration = (uint64_t)ARMING_DURATION_S * 1000000;
    uint16_t current_throttle = DSHOT_THROTTLE_NEUTRAL;
    int current_motor = 0;
    int phase_durations[] = {
        RAMP_DURATION_MS,
        RAMP_DURATION_MS,
        PAUSE_DURATION_MS,
        RAMP_DURATION_MS,
        RAMP_DURATION_MS,
        PAUSE_DURATION_MS
    };

    while (true) {
        uint64_t now = time_us_64();
        uint64_t elapsed_in_state = now - state_start_time;

        if (elapsed_in_state >= current_state_duration) {
            state_start_time = now;
            switch (current_state) {
            case STATE_ARMING:
                current_state = STATE_MOTOR_TEST;
                current_phase = PHASE_RAMP_FORWARD_UP;
                current_state_duration = phase_durations[current_phase] * 1000;
                printf("Arming complete. Testing Motor %d (Pin %d)...\n", 
                       current_motor, MOTOR_PIN_BASE + current_motor);
                printf("  Phase: FORWARD UP\n");
                break;

            case STATE_MOTOR_TEST:
                current_phase++;
                if (current_phase >= 6) {
                    current_motor++;
                    current_phase = PHASE_RAMP_FORWARD_UP;
                    if (current_motor >= NUM_MOTORS) {
                        current_state = STATE_DONE;
                        current_state_duration = -1;
                        printf("All motor tests complete. Idling at neutral.\n");
                        break;
                    } else {
                        printf("Testing Motor %d (Pin %d)...\n", 
                               current_motor, MOTOR_PIN_BASE + current_motor);
                    }
                }
                current_state_duration = phase_durations[current_phase] * 1000;
                const char* phase_names[] = {
                    "FORWARD UP", "FORWARD DOWN", "PAUSE", 
                    "REVERSE UP", "REVERSE DOWN", "PAUSE"
                };
                printf("  Phase: %s\n", phase_names[current_phase]);
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
        case STATE_DONE:
            current_throttle = DSHOT_THROTTLE_NEUTRAL;
            break;
        case STATE_MOTOR_TEST:
            switch (current_phase) {
            case PHASE_RAMP_FORWARD_UP:
                current_throttle = DSHOT_THROTTLE_NEUTRAL + (uint16_t)(100 * progress);
                break;
            case PHASE_RAMP_FORWARD_DOWN:
                current_throttle = (DSHOT_THROTTLE_NEUTRAL + 100) - (uint16_t)(100 * progress);
                break;
            case PHASE_PAUSE_1:
            case PHASE_PAUSE_2:
                current_throttle = DSHOT_THROTTLE_NEUTRAL;
                break;
            case PHASE_RAMP_REVERSE_UP:
                current_throttle = (48) + (uint16_t)(100 * progress);
                break;
            case PHASE_RAMP_REVERSE_DOWN:
                current_throttle = 148 - (uint16_t)(100 * progress);
                break;
            }
            break;
        }

        for (int i = 0; i < NUM_MOTORS; i++) {
            if (current_state == STATE_MOTOR_TEST && i == current_motor) {
                dshot_throttle(&controller, i, current_throttle);
            } else {
                dshot_throttle(&controller, i, DSHOT_THROTTLE_NEUTRAL);
            }
        }
        dshot_loop(&controller);
    }

    return 0;
}
