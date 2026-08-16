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


def test_prerelease_bundle_matches_three_part_mcu_version():
    assert mcu.mcu_versions_match("1.0.3", "1.0.3-rc.1")
    assert not mcu.mcu_versions_match("1.0.2", "1.0.3-rc.1")


def test_prerelease_requires_one_flash_per_exact_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    firmware_dir = tmp_path / "mcu-firmware"
    firmware_dir.mkdir()

    assert mcu.mcu_update_required(McuBoard.PICO, "1.0.3", "1.0.3-rc.1")

    (firmware_dir / ".pico-flashed-version").write_text(
        "1.0.3-rc.1\n", encoding="utf-8"
    )

    assert not mcu.mcu_update_required(McuBoard.PICO, "1.0.3", "1.0.3-rc.1")
    assert mcu.mcu_update_required(McuBoard.PICO, "1.0.3", "1.0.3-rc.2")


def test_stable_same_core_replaces_recorded_prerelease(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    firmware_dir = tmp_path / "mcu-firmware"
    firmware_dir.mkdir()
    marker = firmware_dir / ".pico-flashed-version"
    marker.write_text("1.0.3-rc.2\n", encoding="utf-8")

    assert mcu.mcu_update_required(McuBoard.PICO, "1.0.3", "1.0.3")

    marker.write_text("1.0.3\n", encoding="utf-8")

    assert not mcu.mcu_update_required(McuBoard.PICO, "1.0.3", "1.0.3")


def test_unmarked_matching_stable_does_not_flash(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "mcu-firmware").mkdir()

    assert not mcu.mcu_update_required(McuBoard.PICO2, "1.0.3", "1.0.3")


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
