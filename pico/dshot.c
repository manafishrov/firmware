#include <string.h>
#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/sync.h"
#include "hardware/pio.h"
#include "dshot.pio.h"
#include "dshot.h"

uint dshot_pio_prog_offset = 0;

static void dshot_sm_config_set_pin(struct dshot_controller *controller, int pin)
{
	sm_config_set_out_pins(&controller->c, pin, 1);
	sm_config_set_set_pins(&controller->c, pin, 1);
	sm_config_set_in_pins(&controller->c, pin);
	sm_config_set_jmp_pin(&controller->c, pin);

	pio_gpio_init(controller->pio, pin);
	gpio_set_pulls(pin, true, false);
}


void dshot_controller_init(
	struct dshot_controller *controller,
	uint16_t dshot_speed,
	PIO pio,
	uint8_t sm,
	int pin,
	int channels
) {
	int i;

	memset(controller, 0, sizeof(*controller));
	controller->pio = pio;
	controller->sm = sm;
	controller->num_channels = channels;
	controller->speed = dshot_speed;
	controller->pin = pin;
	for (i = 0; i < controller->num_channels; i++)
		dshot_throttle(controller, i, 0);

	if (dshot_pio_prog_offset == 0)
		dshot_pio_prog_offset = pio_add_program(pio, &pio_dshot_program);

	controller->c =
		pio_dshot_program_get_default_config(dshot_pio_prog_offset);

	sm_config_set_out_shift(&controller->c, false, false, 32);
	sm_config_set_in_shift(&controller->c, false, false, 32);

	dshot_sm_config_set_pin(controller, pin);

	float clkdiv = (float)clock_get_hz(clk_sys) / (1000.0f * (float)dshot_speed * 40.0f);
	sm_config_set_clkdiv(&controller->c, clkdiv);

	pio_sm_init(pio, sm, dshot_pio_prog_offset, &controller->c);
	pio_sm_set_enabled(pio, sm, true);
}


void dshot_register_telemetry_cb(struct dshot_controller *controller, dshot_telemetry_callback_t telemetry_cb, void *context)
{
	controller->telemetry_cb = telemetry_cb;
	controller->telemetry_cb_context = context;
}

static uint32_t dshot_gcr_lookup(int gcr, int *error)
{
	switch (gcr) {
	case 0x19:	return 0;
	case 0x1B:	return 1;
	case 0x12:	return 2;
	case 0x13:	return 3;
	case 0x1D:	return 4;
	case 0x15:	return 5;
	case 0x16:	return 6;
	case 0x17:	return 7;
	case 0x1A:	return 8;
	case 0x09:	return 9;
	case 0x0A:	return 10;
	case 0x0B:	return 11;
	case 0x1E:	return 12;
	case 0x0D:	return 13;
	case 0x0E:	return 14;
	case 0x0F:	return 15;
	}

	*error = 1;
	return 0xfffffff;
}

static void dshot_interpret_erpm_telemetry(struct dshot_controller *controller, uint16_t edt)
{
	struct dshot_motor *motor = &controller->motor[controller->channel];
	enum dshot_telemetry_type type;
	uint16_t e, m;
	int value;

	e = (edt & 0xe000) >> 13;
	m = (edt & 0x1fff) >> 4;

	switch ((edt & 0xf000) >> 12) {
	case 0x2:
		type = DSHOT_TELEMETRY_TEMPERATURE;
		value = m;
		break;
	case 0x4:
		type = DSHOT_TELEMETRY_VOLTAGE;
		value = m / 4;
		break;
	case 0x6:
		type = DSHOT_TELEMETRY_CURRENT;
		value = m;
		break;
	case 0x8:
	case 0xA:
	case 0xC:
	case 0xE:
		motor->stats.rx_bad_type++;
		return;
	default:
		type = DSHOT_TELEMETRY_ERPM;
		value = m << e;
		if (value == 0xff80)
			value = 0;
		else if (value != 0)
			value = (1000000 * 60) / value;
	}

	motor->stats.rx_frames++;
	if (controller->telemetry_cb)
		controller->telemetry_cb(controller->telemetry_cb_context, controller->channel, type, value);
}

static void dshot_receive(struct dshot_controller *controller, uint32_t value)
{
	int bit, i, sum, error = 0;
	uint16_t crc;
	uint32_t gcr, edt;
	struct dshot_motor *motor = &controller->motor[controller->channel];

	if (value == 0) {
		motor->stats.rx_timeout++;
		return;
	}

	gcr = (value ^ (value >> 1));

	edt = (dshot_gcr_lookup((gcr >> 15) & 0x1f, &error) << 12) |
	      (dshot_gcr_lookup((gcr >> 10) & 0x1f, &error) << 8) |
	      (dshot_gcr_lookup((gcr >>  5) & 0x1f, &error) << 4) |
	      (dshot_gcr_lookup((gcr)       & 0x1f, &error));
	edt = edt & 0xffff;

	if (error) {
		motor->stats.rx_bad_gcr++;
		return;
	}

	crc = ~((edt >> 4) ^ (edt >> 8) ^ (edt >> 12)) & 0x0f;

	if (crc != (edt & 0x0f)) {
		motor->stats.rx_bad_crc++;
		return;
	}

	dshot_interpret_erpm_telemetry(controller, edt);
}

static void dshot_cycle_channel(struct dshot_controller *controller)
{
	pio_sm_set_enabled(controller->pio, controller->sm, false);

	controller->channel = (controller->channel + 1) % controller->num_channels;
	dshot_sm_config_set_pin(controller, controller->pin + controller->channel);
	pio_sm_init(controller->pio, controller->sm, dshot_pio_prog_offset, &controller->c);

	pio_sm_set_enabled(controller->pio, controller->sm, true);
}

void dshot_loop_async_start(struct dshot_controller *controller)
{
	struct dshot_motor *motor;

	if (controller->num_channels > 1)
		dshot_cycle_channel(controller);

	motor = &controller->motor[controller->channel];
	if (motor->command_counter > 0) {
		motor->command_counter--;
		if (motor->command_counter == 0)
			motor->frame = motor->last_throttle_frame;
	}

	if (pio_sm_is_tx_fifo_empty(controller->pio, controller->sm)) {
		uint32_t cycles = (25 * controller->speed * 40) / 1000;
		pio_sm_put(controller->pio, controller->sm, ~motor->frame << 16);
		pio_sm_put(controller->pio, controller->sm, cycles);
	}
}

void dshot_loop_async_complete(struct dshot_controller *controller)
{
	uint32_t recv;
	int rxlevel;

	recv = pio_sm_get_blocking(controller->pio, controller->sm);
	dshot_receive(controller, recv);

	if (absolute_time_diff_us(controller->command_last_time, get_absolute_time()) > DSHOT_IDLE_THRESHOLD) {
		for (int i = 0; i < controller->num_channels; i++)
			dshot_throttle(controller, i, 0);
	}

}

void dshot_loop(struct dshot_controller *controller)
{
	dshot_loop_async_start(controller);
	dshot_loop_async_complete(controller);
}

static uint16_t dshot_compute_frame(uint16_t throttle, int telemetry) {
	uint16_t crc, value;

	value = (throttle << 1) | telemetry;

	crc = (value ^ (value >> 4) ^ (value >> 8));

	return (value << 4) | (crc & 0x0F);
}

void dshot_command(struct dshot_controller *controller, uint16_t channel, uint16_t command)
{
	struct dshot_motor *motor;

	if (channel >= controller->num_channels)
		return;

	motor = &controller->motor[channel];

	motor->frame = dshot_compute_frame(command, 1);
	motor->command_counter = 100;

	controller->command_last_time = get_absolute_time();
}

void dshot_throttle(struct dshot_controller *controller, uint16_t channel, uint16_t throttle)
{
	struct dshot_motor *motor;

	if (channel >= controller->num_channels)
		return;

	motor = &controller->motor[channel];

	motor->frame = dshot_compute_frame(throttle, 0);
	motor->last_throttle_frame = motor->frame;
	motor->command_counter = 0;

	controller->command_last_time = get_absolute_time();
}
