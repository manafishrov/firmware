#ifndef DSHOT_H
#define DSHOT_H

#include "hardware/clocks.h"
#include "hardware/pio.h"
#include <stdint.h>

#define DSHOT_MAX_CHANNELS 26
#define DSHOT_IDLE_THRESHOLD (500 * 1000)

enum dshot_telemetry_type {
  DSHOT_TELEMETRY_ERPM,
  DSHOT_TELEMETRY_VOLTAGE,
  DSHOT_TELEMETRY_CURRENT,
  DSHOT_TELEMETRY_TEMPERATURE,
  DSHOT_TELEMETRY_STATUS,
};

enum dshot_commands {
  DSHOT_CMD_BEEP1 = 1,
  DSHOT_CMD_BEEP2 = 2,
  DSHOT_CMD_BEEP3 = 3,
  DSHOT_CMD_BEEP4 = 4,
  DSHOT_CMD_BEEP5 = 5,
  DSHOT_CMD_ESC_INFO = 6,
  DSHOT_CMD_SPIN_DIRECTION_1 = 7,
  DSHOT_CMD_SPIN_DIRECTION_2 = 8,
  DSHOT_CMD_3D_MODE_OFF = 9,
  DSHOT_CMD_3D_MODE_ON = 10,
  DSHOT_CMD_SETTINGS_REQUEST = 11,
  DSHOT_CMD_SAVE_SETTINGS = 12,
  DSHOT_EXTENDED_TELEMETRY_ENABLE = 13,
  DSHOT_EXTENDED_TELEMETRY_DISABLE = 14,
  DSHOT_CMD_SPIN_DIRECTION_NORMAL = 20,
  DSHOT_CMD_SPIN_DIRECTION_REVERSED = 21,
  DSHOT_CMD_LED0_ON = 22,
  DSHOT_CMD_LED1_ON = 23,
  DSHOT_CMD_LED2_ON = 24,
  DSHOT_CMD_LED3_ON = 25,
  DSHOT_CMD_LED0_OFF = 26,
  DSHOT_CMD_LED1_OFF = 27,
  DSHOT_CMD_LED2_OFF = 28,
  DSHOT_CMD_LED3_OFF = 29,
  DSHOT_AUDIO_STREAM_TOGGLE = 30,
  DSHOT_SILENT_MODE_TOGGLE = 31,
  DSHOT_CMD_SIGNAL_LINE_TELEMETRY_DISABLE = 32,
  DSHOT_CMD_SIGNAL_LINE_TELEMETRY_ENABLE = 33,
  DSHOT_CMD_SIGNAL_LINE_CONTINUOUS_ERPM_TELEMETRY = 34,
  DSHOT_CMD_SIGNAL_LINE_CONTINUOUS_ERPM_PERIOD_TELEMETRY = 35,
  DSHOT_CMD_SIGNAL_LINE_TEMPERATURE_TELEMETRY = 42,
  DSHOT_CMD_SIGNAL_LINE_VOLTAGE_TELEMETRY = 43,
  DSHOT_CMD_SIGNAL_LINE_CURRENT_TELEMETRY = 44,
  DSHOT_CMD_SIGNAL_LINE_CONSUMPTION_TELEMETRY = 45,
  DSHOT_CMD_SIGNAL_LINE_ERPM_TELEMETRY = 46,
  DSHOT_CMD_SIGNAL_LINE_ERPM_PERIOD_TELEMETRY = 47,
  DSHOT_MAX_COMMAND = 48,
};

struct dshot_statistics {
  uint32_t tx_frames;
  uint32_t rx_frames;
  uint32_t rx_timeout;
  uint32_t rx_bad_gcr;
  uint32_t rx_bad_crc;
  uint32_t rx_bad_type;
};

struct dshot_motor {
  uint16_t frame;
  uint16_t last_throttle_frame;
  uint8_t command_counter;
  struct dshot_statistics stats;
};

typedef void (*dshot_telemetry_callback_t)(void *context, int channel,
                                           enum dshot_telemetry_type type,
                                           int value);

struct dshot_controller {
  pio_sm_config c;
  PIO pio;
  uint8_t sm;
  uint8_t pin;
  uint8_t num_channels;
  uint8_t channel;
  uint16_t speed;
  struct dshot_motor motor[DSHOT_MAX_CHANNELS];
  absolute_time_t command_last_time;

  dshot_telemetry_callback_t telemetry_cb;
  void *telemetry_cb_context;
};

void dshot_command(struct dshot_controller *controller, uint16_t channel,
                   uint16_t command, uint8_t repeat_count);

void dshot_throttle(struct dshot_controller *controller, uint16_t channel,
                    uint16_t throttle);

void dshot_controller_init(struct dshot_controller *controller,
                           uint16_t dshot_speed, PIO pio, uint8_t sm, int pin,
                           int channels);

void dshot_loop(struct dshot_controller *controller);

void dshot_loop_async_start(struct dshot_controller *controller);

void dshot_loop_async_complete(struct dshot_controller *controller);

void dshot_register_telemetry_cb(struct dshot_controller *controller,
                                 dshot_telemetry_callback_t telemetry_cb,
                                 void *context);

#endif
