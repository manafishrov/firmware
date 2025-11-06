#include "dshot.h"
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "pico/stdlib.h"
#include "pico/time.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define MOTOR0_PIN_BASE 6
#define MOTOR1_PIN_BASE 18
#define NUM_MOTORS_0 4
#define NUM_MOTORS_1 4
#define NUM_MOTORS (NUM_MOTORS_0 + NUM_MOTORS_1)

#define DSHOT_PIO pio0
#define DSHOT_SM_0 0
#define DSHOT_SM_1 1
#define DSHOT_SPEED 300

#define COMM_TIMEOUT_MS 200

#define CMD_THROTTLE_MIN_REVERSE 0
#define CMD_THROTTLE_NEUTRAL 1000
#define CMD_THROTTLE_MAX_FORWARD 2000
#define DSHOT_CMD_NEUTRAL 0
#define DSHOT_CMD_MIN_REVERSE 48
#define DSHOT_CMD_MAX_REVERSE 1047
#define DSHOT_CMD_MIN_FORWARD 1048
#define DSHOT_CMD_MAX_FORWARD 2047

#define TELEMETRY_START_BYTE 0xA5
#define TELEMETRY_PACKET_SIZE 8
#define TELEMETRY_ID_VOLTAGE 0xFF
#define TELEMETRY_TYPE_ERPM 0
#define TELEMETRY_TYPE_VOLTAGE 1
#define TELEMETRY_TYPE_TEMPERATURE 2
#define TELEMETRY_TYPE_CURRENT 3
#define TELEMETRY_TYPE_EDT_STATUS 4

#define INPUT_START_BYTE 0x5A
#define INPUT_PACKET_SIZE (1 + NUM_MOTORS * 2 + 1)

static uint16_t thruster_values[NUM_MOTORS] = {0};
static absolute_time_t last_comm_time;
static bool edt_enabled[NUM_MOTORS] = {false};
static absolute_time_t last_telemetry_time[NUM_MOTORS];

typedef struct {
  uint8_t controller_base_global_id;
} telemetry_context_t;

static telemetry_context_t context0 = {.controller_base_global_id = 0};
static telemetry_context_t context1 = {.controller_base_global_id =
                                           NUM_MOTORS_0};

static uint8_t calculate_checksum(const uint8_t *data, size_t len) {
  uint8_t checksum = 0;
  for (size_t i = 0; i < len; ++i) {
    checksum ^= data[i];
  }
  return checksum;
}

uint16_t translate_throttle_to_dshot(uint16_t cmd_throttle) {
  if (cmd_throttle == CMD_THROTTLE_NEUTRAL) {
    return DSHOT_CMD_NEUTRAL;
  }
  if (cmd_throttle > CMD_THROTTLE_NEUTRAL &&
      cmd_throttle <= CMD_THROTTLE_MAX_FORWARD) {
    return (cmd_throttle - CMD_THROTTLE_NEUTRAL - 1) + DSHOT_CMD_MIN_FORWARD;
  }
  if (cmd_throttle < CMD_THROTTLE_NEUTRAL &&
      cmd_throttle >= CMD_THROTTLE_MIN_REVERSE) {
    return DSHOT_CMD_MAX_REVERSE - cmd_throttle;
  }
  return DSHOT_CMD_NEUTRAL;
}

void send_telemetry(uint8_t motor_id, uint8_t type, int32_t value) {
  uint8_t buf[TELEMETRY_PACKET_SIZE];
  buf[0] = TELEMETRY_START_BYTE;
  buf[1] = motor_id;
  buf[2] = type;
  memcpy(&buf[3], &value, 4);
  buf[TELEMETRY_PACKET_SIZE - 1] =
      calculate_checksum(&buf[0], TELEMETRY_PACKET_SIZE - 1);
  fwrite(buf, 1, TELEMETRY_PACKET_SIZE, stdout);
  fflush(stdout);
}

void telemetry_callback(void *context, int channel,
                        enum dshot_telemetry_type type, int value) {
  telemetry_context_t *ctx = (telemetry_context_t *)context;
  uint8_t global_motor_id = ctx->controller_base_global_id + channel;

  last_telemetry_time[global_motor_id] = get_absolute_time();

  if (type == DSHOT_TELEMETRY_ERPM) {
    send_telemetry(global_motor_id, TELEMETRY_TYPE_ERPM, value);
  } else if (type == DSHOT_TELEMETRY_VOLTAGE) {
    send_telemetry(global_motor_id, TELEMETRY_TYPE_VOLTAGE, value * 4);
  } else if (type == DSHOT_TELEMETRY_TEMPERATURE) {
    send_telemetry(global_motor_id, TELEMETRY_TYPE_TEMPERATURE, value);
  } else if (type == DSHOT_TELEMETRY_CURRENT) {
    send_telemetry(global_motor_id, TELEMETRY_TYPE_CURRENT, value);
  } else if (type == DSHOT_TELEMETRY_STATUS) {
    if (!edt_enabled[global_motor_id]) {
      edt_enabled[global_motor_id] = true;
    }
  }
}

int main() {
  stdio_init_all();

  struct dshot_controller controller0, controller1;
  dshot_controller_init(&controller0, DSHOT_SPEED, DSHOT_PIO, DSHOT_SM_0,
                        MOTOR0_PIN_BASE, NUM_MOTORS_0);
  dshot_register_telemetry_cb(&controller0, telemetry_callback, &context0);
  dshot_controller_init(&controller1, DSHOT_SPEED, DSHOT_PIO, DSHOT_SM_1,
                        MOTOR1_PIN_BASE, NUM_MOTORS_1);
  dshot_register_telemetry_cb(&controller1, telemetry_callback, &context1);

  for (int i = 0; i < NUM_MOTORS; ++i) {
    thruster_values[i] = CMD_THROTTLE_NEUTRAL;
    last_telemetry_time[i] = get_absolute_time();
  }
  last_comm_time = get_absolute_time();

  for (int i = 0; i < NUM_MOTORS; ++i) {
    struct dshot_controller *ctrl =
        (i < NUM_MOTORS_0) ? &controller0 : &controller1;
    int channel = (i < NUM_MOTORS_0) ? i : (i - NUM_MOTORS_0);
    dshot_command(ctrl, channel, DSHOT_CMD_3D_MODE_ON, 10);
    dshot_command(ctrl, channel, DSHOT_CMD_SAVE_SETTINGS, 10);
  }

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
        uint8_t calculated_checksum =
            calculate_checksum(&usb_buf[0], INPUT_PACKET_SIZE - 1);

        if (received_checksum == calculated_checksum) {
          for (int i = 0; i < NUM_MOTORS; ++i) {
            thruster_values[i] =
                ((uint16_t)usb_buf[2 * i + 2] << 8) | usb_buf[2 * i + 1];
          }
          last_comm_time = get_absolute_time();
        }
      }
      usb_idx = 0;
    }

    if (absolute_time_diff_us(last_comm_time, get_absolute_time()) >
        COMM_TIMEOUT_MS * 1000) {
      for (int i = 0; i < NUM_MOTORS; ++i) {
        thruster_values[i] = CMD_THROTTLE_NEUTRAL;
      }
      usb_idx = 0;
    }

    for (int i = 0; i < NUM_MOTORS; ++i) {
      if (absolute_time_diff_us(last_telemetry_time[i], get_absolute_time()) >
          1000000) {
        edt_enabled[i] = false;
      }
    }

    bool all_idle = true;
    for (int i = 0; i < NUM_MOTORS; ++i) {
      if (thruster_values[i] != CMD_THROTTLE_NEUTRAL) {
        all_idle = false;
        break;
      }
    }
    if (all_idle) {
      for (int i = 0; i < NUM_MOTORS; ++i) {
        if (!edt_enabled[i]) {
          struct dshot_controller *ctrl =
              (i < NUM_MOTORS_0) ? &controller0 : &controller1;
          int channel = (i < NUM_MOTORS_0) ? i : (i - NUM_MOTORS_0);
          dshot_command(ctrl, channel, DSHOT_EXTENDED_TELEMETRY_ENABLE, 6);
        }
      }
    }

    for (int i = 0; i < NUM_MOTORS; i++) {
      struct dshot_controller *ctrl =
          (i < NUM_MOTORS_0) ? &controller0 : &controller1;
      int channel = (i < NUM_MOTORS_0) ? i : (i - NUM_MOTORS_0);
      uint16_t dshot_command_val =
          translate_throttle_to_dshot(thruster_values[i]);
      dshot_throttle(ctrl, channel, dshot_command_val);
    }

    dshot_loop(&controller0);
    dshot_loop(&controller1);
  }
  return 0;
}
