from pathlib import Path

from rov_firmware.models.config import McuBoard
from rov_firmware.websocket.receive import mcu


def test_resolve_mcu_firmware_selects_latest_semver(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    firmware_dir = tmp_path / "mcu-firmware"
    firmware_dir.mkdir()
    old = firmware_dir / "pico-v1.0.2.uf2"
    prerelease = firmware_dir / "pico-v1.0.3-rc.1.uf2"
    old.touch()
    prerelease.touch()

    assert mcu.resolve_mcu_firmware(McuBoard.PICO) == (prerelease, "1.0.3-rc.1")


def test_resolve_mcu_firmware_prefers_stable_for_same_core(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    firmware_dir = tmp_path / "mcu-firmware"
    firmware_dir.mkdir()
    (firmware_dir / "pico2-v1.0.3-rc.2.uf2").touch()
    stable = firmware_dir / "pico2-v1.0.3.uf2"
    stable.touch()

    assert mcu.resolve_mcu_firmware(McuBoard.PICO2) == (stable, "1.0.3")


def test_prerelease_bundle_requires_exact_live_version():
    assert mcu.mcu_versions_match("1.0.3-rc.1", "1.0.3-rc.1")
    assert not mcu.mcu_versions_match("1.0.3", "1.0.3-rc.1")
    assert not mcu.mcu_versions_match("1.0.2", "1.0.3-rc.1")


def test_prerelease_update_uses_live_version_without_marker():
    assert mcu.mcu_update_required("1.0.3", "1.0.3-rc.1")
    assert not mcu.mcu_update_required("1.0.3-rc.1", "1.0.3-rc.1")
    assert mcu.mcu_update_required("1.0.3", "1.0.3-rc.2")


def test_stable_same_core_replaces_reported_prerelease():
    assert mcu.mcu_update_required("1.0.3-rc.2", "1.0.3")
    assert not mcu.mcu_update_required("1.0.3", "1.0.3")


def test_legacy_rc_spelling_never_matches():
    assert not mcu.mcu_versions_match("1.0.3-rc1", "1.0.3-rc1")


def test_verified_picotool_write_survives_execute_failure():
    assert mcu._flash_write_completed(return_code=1, verification_succeeded=True)


def test_successful_picotool_exit_does_not_need_fallback():
    assert mcu._flash_write_completed(return_code=0, verification_succeeded=False)


def test_unverified_picotool_write_remains_a_failure():
    assert not mcu._flash_write_completed(return_code=1, verification_succeeded=False)


def test_verification_requires_complete_progress_followed_by_ok():
    reached_100, succeeded = mcu._update_verification_status(
        "Verifying Flash: [==============================] 100%",
        reached_100=False,
        succeeded=False,
    )
    assert reached_100
    assert not succeeded

    reached_100, succeeded = mcu._update_verification_status(
        "  OK",
        reached_100=reached_100,
        succeeded=succeeded,
    )
    assert reached_100
    assert succeeded


def test_load_progress_is_tracked_without_a_toast_when_hidden(monkeypatch):
    toast_calls: list[None] = []
    monkeypatch.setattr(
        mcu, "toast_loading", lambda **_kwargs: toast_calls.append(None)
    )

    percent = mcu._update_load_progress(
        "Loading into Flash: [===============] 50%",
        0,
        "firmware-flash",
        show_toasts=False,
    )

    assert percent == 50
    assert toast_calls == []


def test_load_progress_emits_a_toast_when_visible(monkeypatch):
    toast_calls: list[dict] = []
    monkeypatch.setattr(
        mcu, "toast_loading", lambda **kwargs: toast_calls.append(kwargs)
    )

    percent = mcu._update_load_progress(
        "Loading into Flash: [===============] 50%",
        0,
        "firmware-flash",
        show_toasts=True,
    )

    assert percent == 50
    assert len(toast_calls) == 1
    assert toast_calls[0]["identifier"] == "firmware-flash"
