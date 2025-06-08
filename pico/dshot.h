#ifndef DSHOT_H
#define DSHOT_H

#include "pico/stdlib.h"
#include "hardware/pio.h"

#define DSHOT_MAX_CHANNELS_PER_CONTROLLER 1
#define DSHOT_IDLE_THRESHOLD 200000

#define DSHOT_150    150
#define DSHOT_300    300
#define DSHOT_600    600
#define DSHOT_1200   1200

enum dshot_telemetry_type {
	DSHOT_TELEMETRY_ERPM,
	DSHOT_TELEMETRY_VOLTAGE,
	DSHOT_TELEMETRY_CURRENT,
	DSHOT_TELEMETRY_TEMPERATURE,
};

#define DSHOT_CMD_MOTOR_STOP 0
#define DSHOT_CMD_BEACON1 1
#define DSHOT_CMD_BEACON2 2
#define DSHOT_CMD_BEACON3 3
#define DSHOT_CMD_BEACON4 4
#define DSHOT_CMD_BEACON5 5
#define DSHOT_CMD_ESC_INFO 6
#define DSHOT_CMD_SPIN_DIRECTION_1 7
#define DSHOT_CMD_SPIN_DIRECTION_2 8
#define DSHOT_CMD_3D_MODE_OFF 9
#define DSHOT_CMD_3D_MODE_ON 10
#define DSHOT_CMD_SETTINGS_REQUEST 11
#define DSHOT_CMD_SAVE_SETTINGS 12
#define DSHOT_CMD_EXTENDED_TELEMETRY_ENABLE 13
#define DSHOT_CMD_EXTENDED_TELEMETRY_DISABLE 14
#define DSHOT_CMD_SPIN_DIRECTION_NORMAL 20
#define DSHOT_CMD_SPIN_DIRECTION_REVERSED 21

struct dshot_motor_stats {
	uint32_t rx_frames;
	uint32_t rx_bad_gcr;
	uint32_t rx_bad_crc;
	uint32_t rx_bad_type;
	uint32_t rx_timeout;
};

struct dshot_motor {
	uint16_t frame;
	uint16_t last_throttle_frame;
	int command_counter;
	struct dshot_motor_stats stats;
};

typedef void (*dshot_telemetry_callback_t)(void *context, int controller_channel_idx, enum dshot_telemetry_type type, int value);

struct dshot_controller {
	PIO pio;
	uint8_t sm;
	uint8_t num_channels;
	uint8_t channel;
	int pin;
	uint16_t speed;
	pio_sm_config c;
    uint pio_program_offset;

	struct dshot_motor motor[DSHOT_MAX_CHANNELS_PER_CONTROLLER]; 

	dshot_telemetry_callback_t telemetry_cb;
	void *telemetry_cb_context;

	absolute_time_t command_last_time;
};

void dshot_controller_init(struct dshot_controller *controller, uint16_t dshot_speed, PIO pio, uint8_t sm, int pin, int channels);
void dshot_register_telemetry_cb(struct dshot_controller *controller, dshot_telemetry_callback_t telemetry_cb, void *context);
void dshot_loop_async_start(struct dshot_controller *controller);
void dshot_loop_async_complete(struct dshot_controller *controller);
void dshot_loop(struct dshot_controller *controller);
void dshot_command(struct dshot_controller *controller, uint16_t channel_idx, uint16_t command);
void dshot_throttle(struct dshot_controller *controller, uint16_t channel_idx, uint16_t throttle);

#endif
