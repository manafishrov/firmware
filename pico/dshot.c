#include <string.h>
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/sync.h"
#include "hardware/pio.h"
#include "hardware/clocks.h"
#include "dshot.pio.h"
#include "dshot.h"

static uint dshot_global_pio_offsets[NUM_PIOS];
static bool dshot_global_pio_program_loaded[NUM_PIOS] = {false, false};

extern const pio_program_t pio_dshot_program;

static void dshot_sm_config_set_pin(struct dshot_controller *controller, int pin) {
	sm_config_set_out_pins(&controller->c, pin, 1);
	sm_config_set_set_pins(&controller->c, pin, 1);
	sm_config_set_in_pins(&controller->c, pin);
	sm_config_set_jmp_pin(&controller->c, pin);

	pio_gpio_init(controller->pio, pin);
	gpio_set_pulls(pin, true, false);
}

void dshot_controller_init(struct dshot_controller *controller, uint16_t dshot_speed, PIO pio, uint8_t sm, int pin, int channels) {
	memset(controller, 0, sizeof(*controller));
	controller->pio = pio;
	controller->sm = sm;
	controller->num_channels = channels;
	controller->speed = dshot_speed;
	controller->pin = pin;

	for (int i = 0; i < controller->num_channels; i++) {
		dshot_throttle(controller, i, 0);
    }

	uint pio_idx = pio_get_index(pio);
	if (!dshot_global_pio_program_loaded[pio_idx]) {
        if (!pio_can_add_program(pio, &pio_dshot_program)) {
            panic("DShot Error: Cannot add PIO program to PIO %d. Not enough space.", pio_idx);
        }
		dshot_global_pio_offsets[pio_idx] = pio_add_program(pio, &pio_dshot_program);
		dshot_global_pio_program_loaded[pio_idx] = true;
	}
    controller->pio_program_offset = dshot_global_pio_offsets[pio_idx];

	controller->c = pio_dshot_program_get_default_config(controller->pio_program_offset);

	sm_config_set_out_shift(&controller->c, false, false, 32);
	sm_config_set_in_shift(&controller->c, false, false, 32);

	dshot_sm_config_set_pin(controller, controller->pin + controller->channel);

    float clkdiv = (float)clock_get_hz(clk_sys) / (controller->speed * 1000.f * 40.f);
	sm_config_set_clkdiv(&controller->c, clkdiv);

	pio_sm_init(pio, sm, controller->pio_program_offset, &controller->c);
	pio_sm_set_enabled(pio, sm, true);

    controller->command_last_time = get_absolute_time();
}

void dshot_register_telemetry_cb(struct dshot_controller *controller, dshot_telemetry_callback_t telemetry_cb, void *context) {
	controller->telemetry_cb = telemetry_cb;
	controller->telemetry_cb_context = context;
}

static uint32_t dshot_gcr_lookup(int gcr, int *error) {
	switch (gcr) {
	    case 0x19: return 0;  case 0x1B: return 1;  case 0x12: return 2;  case 0x13: return 3;
	    case 0x1D: return 4;  case 0x15: return 5;  case 0x16: return 6;  case 0x17: return 7;
	    case 0x1A: return 8;  case 0x09: return 9;  case 0x0A: return 10; case 0x0B: return 11;
	    case 0x1E: return 12; case 0x0D: return 13; case 0x0E: return 14; case 0x0F: return 15;
	}
	*error = 1;
	return 0xFFFFFFFF;
}

static void dshot_interpret_erpm_telemetry(struct dshot_controller *controller, uint16_t edt) {
	struct dshot_motor *motor = &controller->motor[controller->channel]; 
	enum dshot_telemetry_type type;
	uint16_t e_val, m_val;
	int value;

	e_val = (edt & 0xE000) >> 13;
	m_val = (edt & 0x1FF0) >> 4;

	switch ((edt & 0xF000) >> 12) {
	    case 0x2:
		    type = DSHOT_TELEMETRY_TEMPERATURE;
		    value = m_val;
		    break;
	    case 0x4:
		    type = DSHOT_TELEMETRY_VOLTAGE;
		    value = m_val / 4;
		    break;
	    case 0x6:
		    type = DSHOT_TELEMETRY_CURRENT;
		    value = m_val;
		    break;
	    case 0x8: case 0xA: case 0xC: case 0xE:
		    motor->stats.rx_bad_type++;
		    return;
	    default:
		    type = DSHOT_TELEMETRY_ERPM;
		    value = m_val << e_val;
		    if (value == 0xFF80) {
			    value = 0;
            } else if (value != 0) {
			    value = (1000000 * 60) / value;
            }
	}

	motor->stats.rx_frames++;
	if (controller->telemetry_cb) {
		controller->telemetry_cb(controller->telemetry_cb_context, controller->channel, type, value);
	}
}

static void dshot_receive(struct dshot_controller *controller, uint32_t raw_value) {
	struct dshot_motor *motor = &controller->motor[controller->channel];
	int error = 0;
	uint16_t calculated_crc;
	uint32_t gcr_frame, edt_frame;

	if (raw_value == 0) {
		motor->stats.rx_timeout++;
		return;
	}

	gcr_frame = (raw_value ^ (raw_value >> 1)) & 0xFFFFF;

	edt_frame = (dshot_gcr_lookup((gcr_frame >> 15) & 0x1F, &error) << 12) |
	            (dshot_gcr_lookup((gcr_frame >> 10) & 0x1F, &error) << 8)  |
	            (dshot_gcr_lookup((gcr_frame >> 5)  & 0x1F, &error) << 4)  |
	            (dshot_gcr_lookup((gcr_frame)       & 0x1F, &error));
	edt_frame &= 0xFFFF;

	if (error) {
		motor->stats.rx_bad_gcr++;
		return;
	}

	calculated_crc = ~((edt_frame >> 12) ^ (edt_frame >> 8) ^ (edt_frame >> 4)) & 0x0F;

	if (calculated_crc != (edt_frame & 0x0F)) {
		motor->stats.rx_bad_crc++;
		return;
	}

	dshot_interpret_erpm_telemetry(controller, edt_frame);
}

static void dshot_cycle_channel(struct dshot_controller *controller) {
	pio_sm_set_enabled(controller->pio, controller->sm, false);

	controller->channel = (controller->channel + 1) % controller->num_channels;
	dshot_sm_config_set_pin(controller, controller->pin + controller->channel);
	pio_sm_init(controller->pio, controller->sm, controller->pio_program_offset, &controller->c);
	pio_sm_set_enabled(controller->pio, controller->sm, true);
}

void dshot_loop_async_start(struct dshot_controller *controller) {
	struct dshot_motor *motor;

	if (controller->num_channels > 1) {
		dshot_cycle_channel(controller);
    }

	motor = &controller->motor[controller->channel];

	if (motor->command_counter > 0) {
		motor->command_counter--;
		if (motor->command_counter == 0) {
			motor->frame = motor->last_throttle_frame;
        }
	}

	if (pio_sm_is_tx_fifo_empty(controller->pio, controller->sm)) {
		pio_sm_put(controller->pio, controller->sm, (~motor->frame) << 16);
        float pio_clk_freq = (float)clock_get_hz(clk_sys) / controller->c.clkdiv;
        uint32_t wait_cycles = (uint32_t)(25.0f * pio_clk_freq / 1000000.0f);
		pio_sm_put(controller->pio, controller->sm, wait_cycles);
	}
}

void dshot_loop_async_complete(struct dshot_controller *controller) {
	uint32_t received_value;

	received_value = pio_sm_get_blocking(controller->pio, controller->sm);
	dshot_receive(controller, received_value);

	if (absolute_time_diff_us(controller->command_last_time, get_absolute_time()) > DSHOT_IDLE_THRESHOLD) {
		for (int i = 0; i < controller->num_channels; i++) {
			dshot_throttle(controller, i, 0);
        }
	}
}

void dshot_loop(struct dshot_controller *controller) {
	dshot_loop_async_start(controller);
	dshot_loop_async_complete(controller);
}

static uint16_t dshot_compute_frame(uint16_t value, int telemetry_request) {
	uint16_t frame;
    uint8_t crc;

	frame = (value << 1) | (telemetry_request ? 1 : 0);

	crc = (frame ^ (frame >> 4) ^ (frame >> 8)) & 0x0F;
	crc = ~crc & 0x0F;

	return (frame << 4) | crc;
}

void dshot_command(struct dshot_controller *controller, uint16_t channel_idx, uint16_t command) {
	struct dshot_motor *motor;

	if (channel_idx >= controller->num_channels) return;
	motor = &controller->motor[channel_idx];

	motor->frame = dshot_compute_frame(command, 1);
	motor->command_counter = 12; 

	controller->command_last_time = get_absolute_time();
}

void dshot_throttle(struct dshot_controller *controller, uint16_t channel_idx, uint16_t throttle) {
	struct dshot_motor *motor;

	if (channel_idx >= controller->num_channels) return;
	motor = &controller->motor[channel_idx];

	motor->frame = dshot_compute_frame(throttle, 0);
	motor->last_throttle_frame = motor->frame;
	motor->command_counter = 0;

	controller->command_last_time = get_absolute_time();
}
