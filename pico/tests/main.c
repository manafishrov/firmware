#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "pico/time.h"
#include "dshot.h"

#define MOTOR0_PIN_BASE 18
#define MOTOR1_PIN_BASE 6
#define NUM_MOTORS_0 4
#define NUM_MOTORS_1 4
#define NUM_MOTORS (NUM_MOTORS_0 + NUM_MOTORS_1)

#define DSHOT_PIO pio0
#define DSHOT_SM_0 0
#define DSHOT_SM_1 1
#define DSHOT_SPEED 300

#define DSHOT_THROTTLE_NEUTRAL 0
#define DSHOT_THROTTLE_MIN_FORWARD 1048
#define DSHOT_THROTTLE_MAX_FORWARD 2047
#define DSHOT_THROTTLE_MIN_REVERSE 48
#define DSHOT_THROTTLE_MAX_REVERSE 1047

#define ARMING_DURATION_S 10
#define RAMP_DURATION_MS 6000
#define PAUSE_DURATION_MS 500

enum test_state {
    STATE_ARMING,
    STATE_ALL_MOTORS_FORWARD,
    STATE_ALL_MOTORS_REVERSE,
    STATE_INDIVIDUAL_MOTOR_FORWARD,
    STATE_INDIVIDUAL_MOTOR_REVERSE,
    STATE_DONE
};

enum motor_test_phase {
    PHASE_RAMP_UP,
    PHASE_RAMP_DOWN,
    PHASE_PAUSE
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

    printf("Pico DShot ROV Motor Test\n");
    printf("------------------------------------\n");
    printf("Testing thrusters on pins 18, 19, 20, 21 and 6, 7, 8, 9\n");
    printf(
        "Power on ESCs now. Arming with neutral signal for %d seconds...\n",
        ARMING_DURATION_S
    );

    struct dshot_controller controller0;
    struct dshot_controller controller1;
    dshot_controller_init(
        &controller0,
        DSHOT_SPEED,
        DSHOT_PIO,
        DSHOT_SM_0,
        MOTOR0_PIN_BASE,
        NUM_MOTORS_0
    );
    dshot_register_telemetry_cb(&controller0, telemetry_callback, NULL);
    dshot_controller_init(
        &controller1,
        DSHOT_SPEED,
        DSHOT_PIO,
        DSHOT_SM_1,
        MOTOR1_PIN_BASE,
        NUM_MOTORS_1
    );
    dshot_register_telemetry_cb(&controller1, telemetry_callback, NULL);

    enum test_state current_state = STATE_ARMING;
    enum motor_test_phase current_phase = PHASE_RAMP_UP;
    uint64_t state_start_time = time_us_64();
    uint64_t current_state_duration = (uint64_t)ARMING_DURATION_S * 1000000;
    uint16_t current_throttle = DSHOT_THROTTLE_NEUTRAL;
    int current_motor_idx = 0;

    int phase_durations_ms[] = {
        RAMP_DURATION_MS,
        RAMP_DURATION_MS,
        PAUSE_DURATION_MS
    };

    const uint16_t MAX_FORWARD_50_PERCENT = DSHOT_THROTTLE_MIN_FORWARD + (DSHOT_THROTTLE_MAX_FORWARD - DSHOT_THROTTLE_MIN_FORWARD) / 2;
    const uint16_t MAX_REVERSE_50_PERCENT = DSHOT_THROTTLE_MIN_REVERSE + (DSHOT_THROTTLE_MAX_REVERSE - DSHOT_THROTTLE_MIN_REVERSE) / 2;


    while (true) {
        uint64_t now = time_us_64();
        uint64_t elapsed_in_state_us = now - state_start_time;

        if (current_state_duration > 0 && elapsed_in_state_us >= current_state_duration) {
            state_start_time = now;
            elapsed_in_state_us = 0;

            bool transition_to_next_phase = true;

            switch (current_state) {
                case STATE_ARMING:
                    current_state = STATE_ALL_MOTORS_FORWARD;
                    current_phase = PHASE_RAMP_UP;
                    current_state_duration = (uint64_t)phase_durations_ms[current_phase] * 1000;
                    printf("Arming complete. Testing all motors forward.\n");
                    printf("  Phase: RAMP UP\n");
                    transition_to_next_phase = false;
                    break;

                case STATE_ALL_MOTORS_FORWARD:
                    if (current_phase == PHASE_RAMP_UP) {
                        current_phase = PHASE_RAMP_DOWN;
                        printf("  Phase: RAMP DOWN\n");
                    } else if (current_phase == PHASE_RAMP_DOWN) {
                        current_phase = PHASE_PAUSE;
                        printf("  Phase: PAUSE\n");
                    } else {
                        current_state = STATE_ALL_MOTORS_REVERSE;
                        current_phase = PHASE_RAMP_UP;
                        printf("Testing all motors reverse.\n");
                        printf("  Phase: RAMP UP\n");
                    }
                    break;

                case STATE_ALL_MOTORS_REVERSE:
                    if (current_phase == PHASE_RAMP_UP) {
                        current_phase = PHASE_RAMP_DOWN;
                        printf("  Phase: RAMP DOWN\n");
                    } else if (current_phase == PHASE_RAMP_DOWN) {
                        current_phase = PHASE_PAUSE;
                        printf("  Phase: PAUSE\n");
                    } else {
                        current_state = STATE_INDIVIDUAL_MOTOR_FORWARD;
                        current_phase = PHASE_RAMP_UP;
                        current_motor_idx = 0;
                        printf("Testing Motor %d (Pin %d) forward.\n", current_motor_idx, (current_motor_idx < NUM_MOTORS_0 ? MOTOR0_PIN_BASE + current_motor_idx : MOTOR1_PIN_BASE + (current_motor_idx - NUM_MOTORS_0)));
                        printf("  Phase: RAMP UP\n");
                    }
                    break;

                case STATE_INDIVIDUAL_MOTOR_FORWARD:
                    if (current_phase == PHASE_RAMP_UP) {
                        current_phase = PHASE_RAMP_DOWN;
                        printf("  Phase: RAMP DOWN\n");
                    } else if (current_phase == PHASE_RAMP_DOWN) {
                        current_phase = PHASE_PAUSE;
                        printf("  Phase: PAUSE\n");
                    } else {
                        current_state = STATE_INDIVIDUAL_MOTOR_REVERSE;
                        current_phase = PHASE_RAMP_UP;
                        printf("Testing Motor %d (Pin %d) reverse.\n", current_motor_idx, (current_motor_idx < NUM_MOTORS_0 ? MOTOR0_PIN_BASE + current_motor_idx : MOTOR1_PIN_BASE + (current_motor_idx - NUM_MOTORS_0)));
                        printf("  Phase: RAMP UP\n");
                    }
                    break;

                case STATE_INDIVIDUAL_MOTOR_REVERSE:
                    if (current_phase == PHASE_RAMP_UP) {
                        current_phase = PHASE_RAMP_DOWN;
                        printf("  Phase: RAMP DOWN\n");
                    } else if (current_phase == PHASE_RAMP_DOWN) {
                        current_phase = PHASE_PAUSE;
                        printf("  Phase: PAUSE\n");
                    } else {
                        current_motor_idx++;
                        if (current_motor_idx < NUM_MOTORS) {
                            current_state = STATE_INDIVIDUAL_MOTOR_FORWARD;
                            current_phase = PHASE_RAMP_UP;
                            printf("Testing Motor %d (Pin %d) forward.\n", current_motor_idx, (current_motor_idx < NUM_MOTORS_0 ? MOTOR0_PIN_BASE + current_motor_idx : MOTOR1_PIN_BASE + (current_motor_idx - NUM_MOTORS_0)));
                            printf("  Phase: RAMP UP\n");
                        } else {
                            current_state = STATE_DONE;
                            printf("All motor tests complete. Idling at neutral.\n");
                            current_state_duration = 0;
                            transition_to_next_phase = false;
                        }
                    }
                    break;

                case STATE_DONE:
                    transition_to_next_phase = false;
                    break;
            }
            if (transition_to_next_phase && current_state != STATE_DONE) {
                 current_state_duration = (uint64_t)phase_durations_ms[current_phase] * 1000;
            }
        }

        float progress = 0.0f;
        if (current_state_duration > 0) {
            progress = (float)elapsed_in_state_us / (float)current_state_duration;
            if (progress > 1.0f) {
                progress = 1.0f;
            }
             if (progress < 0.0f) {
                progress = 0.0f;
            }
        }


        current_throttle = DSHOT_THROTTLE_NEUTRAL;

        switch (current_state) {
            case STATE_ARMING:
                break;
            case STATE_ALL_MOTORS_FORWARD:
                if (current_phase == PHASE_RAMP_UP) {
                    current_throttle = DSHOT_THROTTLE_MIN_FORWARD + (uint16_t)((MAX_FORWARD_50_PERCENT - DSHOT_THROTTLE_MIN_FORWARD) * progress);
                } else if (current_phase == PHASE_RAMP_DOWN) {
                    current_throttle = MAX_FORWARD_50_PERCENT - (uint16_t)((MAX_FORWARD_50_PERCENT - DSHOT_THROTTLE_MIN_FORWARD) * progress);
                }
                break;
            case STATE_ALL_MOTORS_REVERSE:
                if (current_phase == PHASE_RAMP_UP) {
                    current_throttle = DSHOT_THROTTLE_MIN_REVERSE + (uint16_t)((MAX_REVERSE_50_PERCENT - DSHOT_THROTTLE_MIN_REVERSE) * progress);
                } else if (current_phase == PHASE_RAMP_DOWN) {
                    current_throttle = MAX_REVERSE_50_PERCENT - (uint16_t)((MAX_REVERSE_50_PERCENT - DSHOT_THROTTLE_MIN_REVERSE) * progress);
                }
                break;
            case STATE_INDIVIDUAL_MOTOR_FORWARD:
                if (current_phase == PHASE_RAMP_UP) {
                    current_throttle = DSHOT_THROTTLE_MIN_FORWARD + (uint16_t)((MAX_FORWARD_50_PERCENT - DSHOT_THROTTLE_MIN_FORWARD) * progress);
                } else if (current_phase == PHASE_RAMP_DOWN) {
                    current_throttle = MAX_FORWARD_50_PERCENT - (uint16_t)((MAX_FORWARD_50_PERCENT - DSHOT_THROTTLE_MIN_FORWARD) * progress);
                }
                break;
            case STATE_INDIVIDUAL_MOTOR_REVERSE:
                 if (current_phase == PHASE_RAMP_UP) {
                    current_throttle = DSHOT_THROTTLE_MIN_REVERSE + (uint16_t)((MAX_REVERSE_50_PERCENT - DSHOT_THROTTLE_MIN_REVERSE) * progress);
                } else if (current_phase == PHASE_RAMP_DOWN) {
                    current_throttle = MAX_REVERSE_50_PERCENT - (uint16_t)((MAX_REVERSE_50_PERCENT - DSHOT_THROTTLE_MIN_REVERSE) * progress);
                }
                break;
            case STATE_DONE:
                break;
        }
        for (int i = 0; i < NUM_MOTORS; i++) {
            struct dshot_controller* ctrl;
            int channel;
            if (i < NUM_MOTORS_0) {
                ctrl = &controller0;
                channel = i;
            } else {
                ctrl = &controller1;
                channel = i - NUM_MOTORS_0;
            }
            if (current_state == STATE_ALL_MOTORS_FORWARD || current_state == STATE_ALL_MOTORS_REVERSE) {
                dshot_throttle(ctrl, channel, current_throttle);
            } else if (current_state == STATE_INDIVIDUAL_MOTOR_FORWARD || current_state == STATE_INDIVIDUAL_MOTOR_REVERSE) {
                if (i == current_motor_idx) {
                    dshot_throttle(ctrl, channel, current_throttle);
                } else {
                    dshot_throttle(ctrl, channel, DSHOT_THROTTLE_NEUTRAL);
                }
            } else {
                dshot_throttle(ctrl, channel, DSHOT_THROTTLE_NEUTRAL);
            }
        }
        dshot_loop(&controller0);
        dshot_loop(&controller1);
    }

    return 0;
}
