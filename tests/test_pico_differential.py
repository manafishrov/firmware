"""C differential tests against frozen, unmodified Python source, not C goldens."""

import ctypes as ct
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType
from unittest.mock import patch

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from rov_firmware.serial import SerialManager


REFERENCE = Path(__file__).parent / "reference"
HASHES = {
    "constants": "6c97cae92e9c17e516b87c904df8c6f9f9b8add126547c911dca285968b1f772",
    "regulator": "79d27b42808e1d147e8393633f5d2e7afb0d6b6907819b1ec62d16756a40686d",
    "thrusters": "acf72977edc41e07130830f29fac31e07b537c3b5296a0f42a99b78800862d35",
}
V3 = ct.c_float * 3
V4 = ct.c_float * 4
V8 = ct.c_float * 8
M8 = V8 * 8


class Axis(ct.Structure):
    _fields_ = [(name, ct.c_float) for name in ("kp", "ki", "kd", "rate")]


class Settings(ct.Structure):
    _fields_ = [(name, Axis) for name in ("roll", "pitch", "yaw", "depth")] + [
        ("fpv_mode", ct.c_bool),
        ("power", V3),
        ("coefficients", V3),
        ("allocation", M8),
        ("identifiers", ct.c_uint8 * 8),
        ("spin", ct.c_int8 * 8),
        ("nullspace_count", ct.c_uint32),
        ("nullspace", M8),
    ]


class Sample(ct.Structure):
    _fields_ = [("accel", V3), ("gyro", V3)]


class Output(ct.Structure):
    _fields_ = [
        ("current_q", V4),
        ("desired_q", V4),
        ("desired_depth", ct.c_float),
        ("motors", ct.c_uint16 * 8),
        ("work_percent", ct.c_uint8),
    ]


def load_original(name):
    module = ModuleType(f"rov_firmware._reference_{name}")
    module.__package__ = "rov_firmware"
    source = REFERENCE / f"{name}_b62cbee.txt"
    contents = source.read_bytes()
    if hashlib.sha256(contents).hexdigest() != HASHES[name]:
        msg = f"Modified reference snapshot: {name}"
        raise AssertionError(msg)
    exec(compile(contents, str(source), "exec"), module.__dict__)  # noqa: S102 - trusted hash-verified baseline source
    return module


@pytest.mark.parametrize("name", HASHES)
def test_tampered_reference_is_rejected_before_execution(name, tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    (tmp_path / f"{name}_b62cbee.txt").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "raise RuntimeError('tampered reference executed')\n"
    )
    monkeypatch.setattr(sys.modules[__name__], "REFERENCE", tmp_path)
    with pytest.raises(AssertionError, match="Modified reference snapshot"):
        load_original(name)
    assert not marker.exists()


@pytest.fixture
def originals():
    constants = load_original("constants")
    with patch.dict(sys.modules, {"rov_firmware.constants": constants}):
        regulator = load_original("regulator")
        with patch.dict(sys.modules, {"rov_firmware.regulator": regulator}):
            thrusters = load_original("thrusters")
    return regulator, thrusters


@pytest.mark.parametrize("name,digest", HASHES.items())
def test_reference_source_integrity(name, digest):
    assert (
        hashlib.sha256((REFERENCE / f"{name}_b62cbee.txt").read_bytes()).hexdigest()
        == digest
    )


@pytest.fixture(scope="module")
def controller(tmp_path_factory):
    source_env = os.environ.get("PICO_CONTROLLER_SOURCE")
    if not source_env:
        pytest.skip(
            "Set PICO_CONTROLLER_SOURCE to run the actual C-vs-original differential oracle"
        )
    source = Path(source_env).resolve()
    assert source.is_file(), source
    compiler = shutil.which("cc")
    assert compiler, "A host C compiler is required"
    build = tmp_path_factory.mktemp("pico-controller")
    wrapper = build / "wrapper.c"
    wrapper.write_text(
        '#include "controller.h"\n#include <stdlib.h>\n'
        "void *oracle_new(void) { control_state_t *s=calloc(1,sizeof(*s)); control_init(s); return s; }\n"
        "void oracle_free(void *s) { free(s); }\n"
        "void oracle_current(control_state_t *s, const float *q) { for(int i=0;i<4;i++)s->current_q[i]=q[i]; }\n"
        "void oracle_integrals(control_state_t *s,float *out) { for(int i=0;i<3;i++)out[i]=s->attitude_integral[i]; out[3]=s->depth_integral; }\n"
    )
    library = build / "controller.so"
    subprocess.run(  # noqa: S603 - explicit local controller source under test
        [
            compiler,
            "-shared",
            "-fPIC",
            "-O2",
            "-I",
            str(source.parent),
            "-I",
            str(source.parent.parent),
            str(source),
            str(wrapper),
            "-lm",
            "-o",
            str(library),
        ],
        check=True,
    )
    lib = ct.CDLL(str(library))
    lib.oracle_new.restype = ct.c_void_p
    for name in ("oracle_free", "control_init"):
        getattr(lib, name).argtypes = [ct.c_void_p]
    lib.control_apply_settings.argtypes = [ct.c_void_p, ct.POINTER(Settings)]
    lib.control_command.argtypes = [ct.c_void_p, V8, ct.c_float, ct.c_bool, ct.c_bool]
    lib.control_pressure.argtypes = [ct.c_void_p, ct.c_float, ct.c_float]
    lib.control_set_depth.argtypes = [ct.c_void_p, ct.c_float]
    lib.control_set_attitude.argtypes = [ct.c_void_p, V4]
    lib.control_set_attitude.restype = ct.c_bool
    lib.oracle_current.argtypes = [ct.c_void_p, V4]
    lib.oracle_integrals.argtypes = [ct.c_void_p, V4]
    lib.control_step.argtypes = [
        ct.c_void_p,
        ct.POINTER(Sample),
        ct.c_float,
        ct.POINTER(Output),
    ]
    return lib


def native_settings(config):
    s = Settings()
    for name in ("roll", "pitch", "yaw", "depth"):
        axis = getattr(config.regulator, name)
        setattr(s, name, Axis(axis.kp, axis.ki, axis.kd, axis.rate))
    s.fpv_mode = config.regulator.fpv_mode
    s.power = V3(
        config.power.thrusters_limit,
        config.power.actions_limit,
        config.power.regulator_limit,
    )
    c = config.direction_coefficients
    s.coefficients = V3(c.surge, c.sway, c.heave)
    s.allocation = M8(*(V8(*row) for row in config.thruster_allocation))
    s.identifiers[:] = config.thruster_pin_setup.identifiers.tolist()
    s.spin[:] = config.thruster_pin_setup.spin_directions.tolist()
    s.nullspace_count = len(config.nullspace_vectors)
    for index, row in enumerate(config.nullspace_vectors):
        s.nullspace[index] = V8(*row)
    return s


class OriginalMultirate:
    """Schedule original methods; all numerical operations remain baseline code."""

    def __init__(self, state, originals):
        self.regulator_module, self.thruster_module = originals
        self.state = state
        self.regulator = self.regulator_module.Regulator(state)
        self.thrusters = self.thruster_module.Thrusters(
            state, SerialManager(state), self.regulator
        )
        self.direction = np.zeros(8, dtype=np.float32)
        self.depth_actuation = 0.0
        self.decay = False

    def command(self, direction, dt, stabilization, depth):
        previous_depth = self.state.system_status.depth_hold
        self.state.system_status.auto_stabilization = stabilization
        self.state.system_status.depth_hold = depth
        if depth and not previous_depth:
            pending = self.state.regulator.pending_desired_depth
            self.state.regulator.desired_depth = (
                self.state.pressure.depth if pending is None else pending
            )
        if not depth:
            self.state.regulator.pending_desired_depth = None
        r = self.regulator
        self.direction = np.array(direction, dtype=np.float32)
        r.delta_t_run_regulator = self.regulator_module._clamp_dt(dt)
        r._handle_edges()
        r._update_desired_from_direction_vector(self.direction)
        if depth:
            self.depth_actuation = r._handle_depth_hold(self.direction[2])
        self.decay = True

    def step(self, accel, gyro, dt):
        r = self.regulator
        r.delta_t_run_regulator = dt
        r.gyro_rad_s[:] = gyro  # Baseline copies PID derivative before AHRS rejection.
        with patch.object(
            self.regulator_module,
            "_clamp_dt",
            lambda value: float(np.clip(value, 0.001, 0.02)),
        ):
            r.ahrs.update(
                np.array(gyro, dtype=np.float32), np.array(accel, dtype=np.float32), dt
            )
        direction = self.direction.copy()
        regulation = np.zeros(8, dtype=np.float32)
        if self.state.system_status.depth_hold:
            regulation[:3] = r._transform_movement_vector_world_to_body(
                np.array([0, 0, self.depth_actuation], dtype=np.float32)
            )
            direction[2] = 0
            direction[:3] = r._transform_movement_vector_world_to_body(
                direction[:3].copy()
            )
        if self.state.system_status.auto_stabilization:
            regulation[3:6] = r._handle_stabilization(direction[3:6])
            direction[3:6] = 0
        unlimited = direction + regulation
        work = (
            self.thrusters._calculate_work_indicator_percentage_from_direction_vector(
                unlimited
            )
        )
        r._scale_regulator_direction_vector(regulation)
        r._scale_direction_vector_with_user_max_power(direction)
        thrust = self.thrusters._create_thrust_vector_from_direction_vector(
            direction + regulation
        )
        with patch.object(
            self.thruster_module, "NV_DECAY_RATE", 0.001 if self.decay else 0
        ):
            self.thrusters._remove_deadzone_using_nullspace(thrust)
        self.decay = False
        self.thrusters._reorder_thrust_vector(thrust)
        self.thrusters._correct_thrust_vector_spin_directions(thrust)
        self.thrusters._clip_thrust_vector(thrust)
        return (
            r.ahrs.current_attitude.as_quat(),
            r.desired_attitude.as_quat(),
            self.thrusters._compute_thrust_values(thrust),
            work,
        )


def quaternion_distance(a, b):
    return float((Rotation.from_quat(a).inv() * Rotation.from_quat(b)).magnitude())


@pytest.mark.parametrize(
    "fpv,depth,stabilization",
    [
        (False, False, True),
        (True, False, True),
        (False, True, True),
        (True, True, True),
        (False, True, False),
        (False, False, False),
    ],
)
def test_c_matches_original_multirate_trajectory(  # noqa: PLR0913, PLR0915 - paired fixture inputs and stepwise oracle assertions
    controller, originals, rov_state, fpv, depth, stabilization
):
    config = rov_state.rov_config
    config.regulator.fpv_mode = fpv
    config.thruster_pin_setup.identifiers = np.array(
        [7, 0, 4, 3, 1, 6, 2, 5], dtype=np.int8
    )
    config.thruster_pin_setup.spin_directions = np.array(
        [-1, 1, -1, 1, 1, -1, 1, -1], dtype=np.int8
    )
    config.direction_coefficients.surge = 0.0
    config.direction_coefficients.sway = 0.7
    config.power.thrusters_limit = 22
    config.power.actions_limit = 71
    config.power.regulator_limit = 13
    config.thruster_allocation[0, 6] = 0.4
    config.thruster_allocation[7, 7] = -0.8
    original = OriginalMultirate(rov_state, originals)
    handle = controller.oracle_new()
    try:
        controller.control_apply_settings(handle, ct.byref(native_settings(config)))
        out = Output()
        rng = np.random.default_rng(90210)
        command_index = -1
        pressure_index = -1
        for tick in range(2500):
            t = tick / 500
            pi = tick * 15 // 500
            if pi != pressure_index:
                pressure_index = pi
                actual_depth = float(np.float32(0.3 + 0.1 * np.sin(t)))
                change = float(np.float32(0.1 * np.cos(t)))
                rov_state.pressure.depth = actual_depth
                rov_state.pressure.depth_change = change
                controller.control_pressure(handle, actual_depth, change)
            ci = tick * 60 // 500
            if ci != command_index:
                command_index = ci
                direction = rng.uniform(-0.4, 0.4, 8).astype(np.float32)
                if ci % 5 == 0:
                    direction[3:6] = [0.199999, 0, 0]
                if ci % 7 == 0:
                    direction[3:6] = [0.2, 0, 0]
                enabled = stabilization and not (90 <= ci < 100)
                original.command(direction, 1 / 60, enabled, depth)
                controller.control_command(
                    handle, V8(*direction), 1 / 60, enabled, depth
                )
            gyro = np.array([0.2 * np.sin(t), -0.1 * np.cos(t), 0.3], dtype=np.float32)
            accel = np.array([0.03 * np.sin(t), 0.05, -9.81], dtype=np.float32)
            expected_q, expected_target, motors, work = original.step(
                accel, gyro, 1 / 500
            )
            sample = Sample(V3(*accel), V3(*gyro))
            controller.control_step(handle, ct.byref(sample), 1 / 500, ct.byref(out))
            assert quaternion_distance(expected_q, out.current_q) < 3e-5, (
                tick,
                "actual",
            )
            assert quaternion_distance(expected_target, out.desired_q) < 3e-5, (
                tick,
                "desired",
            )
            np.testing.assert_allclose(
                out.desired_depth,
                rov_state.regulator.desired_depth
                if depth
                else rov_state.pressure.depth,
                atol=2e-5,
                rtol=2e-5,
            )
            # Binary32 intermediate rounding can straddle an integer truncation boundary.
            np.testing.assert_allclose(
                list(out.motors), motors, atol=1, rtol=0, err_msg=f"tick={tick}"
            )
            assert abs(out.work_percent - work) <= 1, tick
            integral = V4()
            controller.oracle_integrals(handle, integral)
            np.testing.assert_allclose(
                list(integral)[:3],
                original.regulator.integral_attitude_rad,
                atol=3e-5,
                rtol=2e-5,
            )
            np.testing.assert_allclose(
                integral[3], original.regulator.integral_depth, atol=3e-5, rtol=2e-5
            )
    finally:
        controller.oracle_free(handle)


@pytest.mark.parametrize("dt", [1 / 60, 1 / 500])
@pytest.mark.parametrize(
    "angles",
    [
        (179.999, 0, 0),
        (-179.999, 0, 0),
        (0, 79.999, 179),
        (0, -79.999, -179),
        (179, 80, 180),
    ],
)
def test_same_dt_shortest_quaternion_and_pitch_boundary(
    controller, originals, rov_state, dt, angles
):
    original = OriginalMultirate(rov_state, originals)
    handle = controller.oracle_new()
    try:
        controller.control_apply_settings(
            handle, ct.byref(native_settings(rov_state.rov_config))
        )
        zero = np.zeros(8, dtype=np.float32)
        original.command(zero, 1 / 60, True, False)
        controller.control_command(handle, V8(*zero), 1 / 60, True, False)
        target = Rotation.from_euler("ZYX", angles, degrees=True)
        original.regulator.desired_attitude = target
        # The opposite quaternion sign must produce the same shortest error.
        assert controller.control_set_attitude(handle, V4(*(-target.as_quat())))
        out = Output()
        sample = Sample(V3(0, 0, -9.81), V3(0, 0, 0))
        for tick in range(30):
            if tick == 10:
                direction = np.array([0, 0, 0, 1, 0.4, 0.3, 0, 0], dtype=np.float32)
                original.command(direction, 1 / 60, True, False)
                controller.control_command(handle, V8(*direction), 1 / 60, True, False)
            actual, desired, motors, _ = original.step(sample.accel, sample.gyro, dt)
            controller.control_step(handle, ct.byref(sample), dt, ct.byref(out))
            assert quaternion_distance(actual, out.current_q) < 3e-5
            assert quaternion_distance(desired, out.desired_q) < 3e-5
            np.testing.assert_allclose(list(out.motors), motors, atol=1, rtol=0)
    finally:
        controller.oracle_free(handle)


def test_sequential_nullspace_history_and_same_count_updates(
    controller, originals, rov_state
):
    config = rov_state.rov_config
    config.nullspace_vectors = [
        np.array([1, -1, 0, 0, 0, 0, 1, -1], dtype=np.float32),
        np.array([0.5, 0.5, 0, 0, 0, 0, -0.5, -0.5], dtype=np.float32),
    ]
    original = OriginalMultirate(rov_state, originals)
    handle = controller.oracle_new()
    try:
        controller.control_apply_settings(handle, ct.byref(native_settings(config)))
        sample = Sample(V3(0, 0, -9.81), V3(0, 0, 0))
        out = Output()
        for tick in range(1000):
            if tick in (350, 700):
                if tick == 350:
                    config.nullspace_vectors[0] *= -1  # Same count must retain history.
                else:
                    config.nullspace_vectors.append(np.zeros(8, dtype=np.float32))
                controller.control_apply_settings(
                    handle, ct.byref(native_settings(config))
                )
            if tick % 8 == 0:
                direction = np.zeros(8, dtype=np.float32)
                direction[0] = 0.03 * np.sin(tick / 70)
                direction[1] = 0.01 * np.cos(tick / 55)
                original.command(direction, 1 / 60, True, False)
                controller.control_command(handle, V8(*direction), 1 / 60, True, False)
            _, _, motors, _ = original.step(sample.accel, sample.gyro, 1 / 500)
            controller.control_step(handle, ct.byref(sample), 1 / 500, ct.byref(out))
            np.testing.assert_allclose(
                list(out.motors), motors, atol=1, rtol=0, err_msg=f"NV tick={tick}"
            )
    finally:
        controller.oracle_free(handle)


def test_integral_windup_clips_match_original(controller, originals, rov_state):
    original = OriginalMultirate(rov_state, originals)
    handle = controller.oracle_new()
    try:
        controller.control_apply_settings(
            handle, ct.byref(native_settings(rov_state.rov_config))
        )
        zero = np.zeros(8, dtype=np.float32)
        original.command(zero, 1 / 60, True, True)
        controller.control_command(handle, V8(*zero), 1 / 60, True, True)
        target = Rotation.from_euler("ZYX", [100, 30, 80], degrees=True)
        original.regulator.desired_attitude = target
        assert controller.control_set_attitude(handle, V4(*target.as_quat()))
        rov_state.regulator.desired_depth = 10
        controller.control_set_depth(handle, 10)
        sample = Sample(V3(0, 0, -9.81), V3(0, 0, 0))
        out = Output()
        for tick in range(3000):
            if tick % 8 == 0:
                original.command(zero, 1 / 60, True, True)
                controller.control_command(handle, V8(*zero), 1 / 60, True, True)
            original.step(sample.accel, sample.gyro, 1 / 500)
            controller.control_step(handle, ct.byref(sample), 1 / 500, ct.byref(out))
        integral = V4()
        controller.oracle_integrals(handle, integral)
        np.testing.assert_allclose(
            list(integral)[:3], original.regulator.integral_attitude_rad, atol=3e-5
        )
        assert integral[3] == original.regulator.integral_depth == 3
        assert max(abs(value) for value in integral[:3]) == pytest.approx(
            np.deg2rad(100), abs=1e-6
        )
    finally:
        controller.oracle_free(handle)


@pytest.mark.parametrize(
    "accel,gyro",
    [
        ([0, 0, 0], [0.1, 0.2, 0.3]),
        ([float("nan"), 0, 0], [0.2, -0.1, 0.3]),
        ([0, 0, -9.81], [19, 0.2, 0.3]),
        ([0, 0, -0.0009], [0.1, 0, 0]),
    ],
)
def test_gyro_only_and_rejected_gyro_derivative_match_original(
    controller, originals, rov_state, accel, gyro
):
    original = OriginalMultirate(rov_state, originals)
    handle = controller.oracle_new()
    try:
        controller.control_apply_settings(
            handle, ct.byref(native_settings(rov_state.rov_config))
        )
        zero = np.zeros(8, dtype=np.float32)
        original.command(zero, 1 / 60, True, False)
        controller.control_command(handle, V8(*zero), 1 / 60, True, False)
        sample = Sample(V3(*accel), V3(*gyro))
        out = Output()
        for _ in range(5):
            actual, desired, motors, work = original.step(
                sample.accel, sample.gyro, 1 / 500
            )
            controller.control_step(handle, ct.byref(sample), 1 / 500, ct.byref(out))
            assert quaternion_distance(actual, out.current_q) < 3e-5
            assert quaternion_distance(desired, out.desired_q) < 3e-5
            np.testing.assert_allclose(list(out.motors), motors, atol=1, rtol=0)
            assert abs(work - out.work_percent) <= 1
    finally:
        controller.oracle_free(handle)
