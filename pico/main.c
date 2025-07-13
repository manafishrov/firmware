#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "pico/time.h"
#include "dshot.h"

#define MOTOR0_PIN_BASE 6
#define MOTOR1_PIN_BASE 18
#define NUM_MOTORS_0 4
#define NUM_MOTORS_1 4
#define NUM_MOTORS (NUM_MOTORS_0 + NUM_MOTORS_1)

#define DSHOT_PIO pio0
#define DSHOT_SM_0 0
#define DSHOT_SM_1 1
#define DSHOT_SPEED 300

#define ARMING_DURATION_MS 10000
#define COMM_TIMEOUT_MS 200

#define CMD_THROTTLE_MIN_REVERSE 0
#define CMD_THROTTLE_NEUTRAL 1000
#define CMD_THROTTLE_MAX_FORWARD 2000
#define DSHOT_CMD_NEUTRAL 0
#define DSHOT_CMD_MIN_REVERSE 48
#define DSHOT_CMD_MAX_REVERSE 1047
#define DSHOT_CMD_MIN_FORWARD 1048
#define DSHOT_CMD_MAX_FORWARD 2047

static uint16_t thruster_values[NUM_MOTORS] = {0};
static absolute_time_t last_comm_time;

uint16_t translate_throttle_to_dshot(uint16_t cmd_throttle) {
    if (cmd_throttle == CMD_THROTTLE_NEUTRAL) {
        return DSHOT_CMD_NEUTRAL;
    }
    if (cmd_throttle > CMD_THROTTLE_NEUTRAL && cmd_throttle <= CMD_THROTTLE_MAX_FORWARD) {
        return (cmd_throttle - CMD_THROTTLE_NEUTRAL - 1) + DSHOT_CMD_MIN_FORWARD;
    }
    if (cmd_throttle < CMD_THROTTLE_NEUTRAL && cmd_throttle >= CMD_THROTTLE_MIN_REVERSE) {
        return DSHOT_CMD_MAX_REVERSE - cmd_throttle;
    }
    return DSHOT_CMD_NEUTRAL;
}

void telemetry_callback(void *context, int channel, enum dshot_telemetry_type type, int value) {
    uint8_t buf[6];
    buf[0] = (uint8_t)channel;
    buf[1] = (uint8_t)type;
    int32_t v = value;
    memcpy(&buf[2], &v, 4);
    fwrite(buf, 1, 6, stdout);
    fflush(stdout);
    (void)context;
}

int main() {
    stdio_init_all();

    struct dshot_controller controller0, controller1;
    dshot_controller_init(&controller0, DSHOT_SPEED, DSHOT_PIO, DSHOT_SM_0, MOTOR0_PIN_BASE, NUM_MOTORS_0);
    dshot_register_telemetry_cb(&controller0, telemetry_callback, NULL);
    dshot_controller_init(&controller1, DSHOT_SPEED, DSHOT_PIO, DSHOT_SM_1, MOTOR1_PIN_BASE, NUM_MOTORS_1);
    dshot_register_telemetry_cb(&controller1, telemetry_callback, NULL);

    absolute_time_t arm_until = make_timeout_time_ms(ARMING_DURATION_MS);
    while (absolute_time_diff_us(get_absolute_time(), arm_until) > 0) {
        for (int i = 0; i < NUM_MOTORS; i++) {
            struct dshot_controller* ctrl = (i < NUM_MOTORS_0) ? &controller0 : &controller1;
            int channel = (i < NUM_MOTORS_0) ? i : (i - NUM_MOTORS_0);
            dshot_throttle(ctrl, channel, DSHOT_CMD_NEUTRAL);
        }
        dshot_loop(&controller0);
        dshot_loop(&controller1);
    }

    for (int i = 0; i < NUM_MOTORS; ++i) {
        thruster_values[i] = CMD_THROTTLE_NEUTRAL;
    }
    last_comm_time = get_absolute_time();

    static uint8_t usb_buf[NUM_MOTORS * 2];
    static size_t usb_idx = 0;

    while (true) {
        int c = getchar_timeout_us(0);
        while (c != PICO_ERROR_TIMEOUT) {
            if (usb_idx < sizeof(usb_buf)) {
                usb_buf[usb_idx++] = (uint8_t)c;
            } else {
                usb_idx = 0; 
            }
            c = getchar_timeout_us(0);
        }

        if (usb_idx >= sizeof(usb_buf)) {
            for (int i = 0; i < NUM_MOTORS; ++i) {
                thruster_values[i] = ((uint16_t)usb_buf[2*i+1] << 8) | usb_buf[2*i];
            }
            last_comm_time = get_absolute_time();
            usb_idx = 0;
        }

        if (absolute_time_diff_us(last_comm_time, get_absolute_time()) > COMM_TIMEOUT_MS * 1000) {
            for (int i = 0; i < NUM_MOTORS; ++i) {
                thruster_values[i] = CMD_THROTTLE_NEUTRAL;
            }
            usb_idx = 0;
        }

        for (int i = 0; i < NUM_MOTORS; i++) {
            struct dshot_controller* ctrl = (i < NUM_MOTORS_0) ? &controller0 : &controller1;
            int channel = (i < NUM_MOTORS_0) ? i : (i - NUM_MOTORS_0);
            uint16_t dshot_command = translate_throttle_to_dshot(thruster_values[i]);
            dshot_throttle(ctrl, channel, dshot_command);
        }

        dshot_loop(&controller0);
        dshot_loop(&controller1);
    }
    return 0;
}
