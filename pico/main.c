#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "hardware/uart.h"
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

#define UART_ID uart0
#define UART_TX_PIN 0
#define UART_RX_PIN 1
#define UART_BAUD 115200

#define ARMING_DURATION_MS 10000
#define UART_TIMEOUT_MS 200

static uint16_t thruster_values[NUM_MOTORS] = {0};
static absolute_time_t last_uart_time;

void telemetry_callback(void *context, int channel, enum dshot_telemetry_type type, int value) {
    uint8_t buf[6];
    buf[0] = (uint8_t)channel;
    buf[1] = (uint8_t)type;
    int32_t v = value;
    memcpy(&buf[2], &v, 4);
    uart_write_blocking(UART_ID, buf, 6);
}

void uart_init_and_setup() {
    uart_init(UART_ID, UART_BAUD);
    gpio_set_function(UART_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(UART_RX_PIN, GPIO_FUNC_UART);
}

int uart_read_packet(uint8_t *buf, size_t len, uint32_t timeout_ms) {
    absolute_time_t deadline = make_timeout_time_ms(timeout_ms);
    size_t recvd = 0;
    while (recvd < len) {
        while (uart_is_readable(UART_ID) && recvd < len) {
            buf[recvd++] = uart_getc(UART_ID);
            last_uart_time = get_absolute_time();
        }
        if (recvd < len && absolute_time_diff_us(get_absolute_time(), deadline) < 0)
            return 0;
    }
    return 1;
}

int main() {
    stdio_init_all();
    uart_init_and_setup();

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
            dshot_throttle(ctrl, channel, 0);
        }
        dshot_loop(&controller0);
        dshot_loop(&controller1);
    }
    for (int i = 0; i < NUM_MOTORS; ++i) thruster_values[i] = 0;
    last_uart_time = get_absolute_time();

    while (true) {
        uint8_t buf[NUM_MOTORS * 2];
        if (uart_is_readable(UART_ID)) {
            size_t idx = 0;
            while (idx < sizeof(buf)) {
                if (!uart_is_readable(UART_ID)) break;
                buf[idx++] = uart_getc(UART_ID);
            }
            if (idx == sizeof(buf)) {
                for (int i = 0; i < NUM_MOTORS; ++i)
                    thruster_values[i] = ((uint16_t)buf[2*i+1] << 8) | buf[2*i];
                last_uart_time = get_absolute_time();
            }
        }
        if (absolute_time_diff_us(last_uart_time, get_absolute_time()) > UART_TIMEOUT_MS * 1000) {
            for (int i = 0; i < NUM_MOTORS; ++i) thruster_values[i] = 0;
        }
        for (int i = 0; i < NUM_MOTORS; i++) {
            struct dshot_controller* ctrl = (i < NUM_MOTORS_0) ? &controller0 : &controller1;
            int channel = (i < NUM_MOTORS_0) ? i : (i - NUM_MOTORS_0);
            dshot_throttle(ctrl, channel, thruster_values[i]);
        }
        dshot_loop(&controller0);
        dshot_loop(&controller1);
    }
    return 0;
}
