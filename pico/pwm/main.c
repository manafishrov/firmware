#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/pwm.h"
#include "hardware/clocks.h"
#include "pwm.h"

#define NUM_MOTORS 8
#define PWM_MIN 1000
#define PWM_NEUTRAL 1500
#define PWM_MAX 2000

#define TELEMETRY_START_BYTE 0xA5
#define TELEMETRY_PACKET_SIZE 7

#define INPUT_START_BYTE 0x5A
#define INPUT_PACKET_SIZE (1 + NUM_MOTORS * 2 + 1)

static uint16_t thruster_values[NUM_MOTORS] = {PWM_NEUTRAL};
static absolute_time_t last_comm_time;

uint8_t calculate_checksum(const uint8_t* data, size_t len) {
    uint8_t checksum = 0;
    for (size_t i = 0; i < len; ++i) {
        checksum ^= data[i];
    }
    return checksum;
}

void send_pwm_telemetry(uint8_t motor_id) {
    uint8_t buf[TELEMETRY_PACKET_SIZE];
    buf[0] = TELEMETRY_START_BYTE;
    buf[1] = motor_id;
    int32_t erpm = 0;
    memcpy(&buf[2], &erpm, 4);
    buf[TELEMETRY_PACKET_SIZE - 1] = calculate_checksum(buf, TELEMETRY_PACKET_SIZE - 1);
    fwrite(buf, 1, TELEMETRY_PACKET_SIZE, stdout);
    fflush(stdout);
}

int main() {
    stdio_init_all();
    struct pwm_controller controller;
    uint pins[NUM_MOTORS] = {6, 7, 8, 9, 18, 19, 20, 21};
    for (int i = 0; i < NUM_MOTORS; ++i) {
        thruster_values[i] = PWM_NEUTRAL;
    }
    pwm_controller_init(&controller, pins, NUM_MOTORS);
    last_comm_time = get_absolute_time();

    static uint8_t usb_buf[INPUT_PACKET_SIZE];
    static size_t usb_idx = 0;

    while (true) {
        int c = getchar_timeout_us(0);
        while (c != PICO_ERROR_TIMEOUT) {
            if (usb_idx == 0 && (uint8_t)c != INPUT_START_BYTE) {
                usb_idx = 0;
            } else if (usb_idx < sizeof(usb_buf)) {
                usb_buf[usb_idx++] = (uint8_t)c;
            } else {
                usb_idx = 0;
            }
            c = getchar_timeout_us(0);
        }
        if (usb_idx >= sizeof(usb_buf)) {
            if (usb_buf[0] == INPUT_START_BYTE) {
                uint8_t received_checksum = usb_buf[INPUT_PACKET_SIZE - 1];
                uint8_t calculated_checksum = calculate_checksum(usb_buf, INPUT_PACKET_SIZE - 1);
                if (received_checksum == calculated_checksum) {
                    for (int i = 0; i < NUM_MOTORS; ++i) {
                        thruster_values[i] = ((uint16_t)usb_buf[2*i+2] << 8) | usb_buf[2*i+1];
                    }
                    last_comm_time = get_absolute_time();
                }
            }
            usb_idx = 0;
        }
        if (absolute_time_diff_us(last_comm_time, get_absolute_time()) > 200 * 1000) {
            for (int i = 0; i < NUM_MOTORS; ++i) {
                thruster_values[i] = PWM_NEUTRAL;
            }
            usb_idx = 0;
        }
        for (int i = 0; i < NUM_MOTORS; ++i) {
            pwm_set_throttle(&controller, i, thruster_values[i]);
            send_pwm_telemetry(i);
        }
    }
    return 0;
}

