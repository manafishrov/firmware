"""Static assertions checked by ty alongside runtime identity regressions."""

from typing import TYPE_CHECKING, assert_type

from manafish_sdk import Context, RovState
from rov_firmware.models.sensors import ImuData, PressureData


if TYPE_CHECKING:

    def check_sdk_types(ctx: Context) -> None:
        assert_type(ctx.rov, RovState)
        assert_type(ctx.rov.pressure, PressureData)
        assert_type(ctx.rov.imu, ImuData)
        assert_type(ctx.rov.pressure.depth, float)
        assert_type(ctx.rov.system_status.depth_hold, bool)
        assert_type(ctx.rov.regulator.pending_desired_depth, float | None)
        assert_type(ctx.rov.mcu_telemetry.erpm, list[int])
