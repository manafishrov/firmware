"""HTTP firmware update server (RAUC bundle staging + health + rollback)."""

import asyncio
import json
from pathlib import Path
import shutil
import tempfile
from typing import cast

from .constants import (
    FIRMWARE_UPDATE_BUNDLE_SUFFIX,
    FIRMWARE_UPDATE_CHUNK_SIZE,
    FIRMWARE_UPDATE_DIR,
    FIRMWARE_UPDATE_FREE_SPACE_MARGIN_BYTES,
    FIRMWARE_UPDATE_MAX_HEADER_BYTES,
    FIRMWARE_UPDATE_PORT,
    FIRMWARE_UPDATE_RAUC_BIN,
    FIRMWARE_UPDATE_REQUEST_PATH,
    FIRMWARE_UPDATE_STATUS_PATH,
    FIRMWARE_UPDATE_SYSTEMCTL_BIN,
    FIRMWARE_UPDATE_TOAST_ID,
)
from .log import log_error, log_info, log_warn
from .models.toast import ToastContent
from .rov_state import RovState
from .toast import toast_error, toast_loading, toast_success


_PHASE_MESSAGE_KEYS: dict[str, str] = {
    "verifying": "toasts_firmware_update_installing",
    "installing": "toasts_firmware_update_installing",
    "rebooting": "toasts_firmware_update_rebooting",
    "awaiting-mark-good": "toasts_firmware_update_awaiting_mark_good",
}

_PHASE_DESCRIPTION_KEYS: dict[str, str] = {
    "verifying": "toasts_firmware_update_rover_verifying_description",
    "installing": "toasts_firmware_update_rover_installing_description",
    "rebooting": "toasts_firmware_update_rebooting_description",
    "awaiting-mark-good": "toasts_firmware_update_awaiting_mark_good_description",
}

_TERMINAL_PHASES: frozenset[str] = frozenset({"completed", "failed", "rolled-back"})


class HttpUpdateServer:
    """HTTP server for staging signed RAUC firmware bundles and exposing health/rollback."""

    def __init__(self, state: RovState) -> None:
        """Initialize the update upload server."""
        self.state: RovState = state
        self.server: asyncio.Server | None = None
        self._last_status: str | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def initialize(self) -> None:
        """Start the HTTP update server bound to all interfaces.

        Bind to 0.0.0.0 so the on-device rauc-mark-good probe (running as root
        on localhost) and the LAN-attached app share a single listener.
        """
        FIRMWARE_UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        self.server = await asyncio.start_server(
            self._handle_client,
            host="0.0.0.0",  # noqa: S104
            port=FIRMWARE_UPDATE_PORT,
        )
        log_info(
            f"Firmware update HTTP server started on 0.0.0.0:{FIRMWARE_UPDATE_PORT}"
        )

    async def wait_closed(self) -> None:
        """Wait for the HTTP server to close."""
        if self.server:
            await self.server.serve_forever()

    async def watch_status_loop(self) -> None:
        """Forward installer status changes to the app over the existing toast websocket."""
        while True:
            try:
                await self._emit_status_if_changed()
            except Exception as exc:
                log_warn(f"Failed to read firmware update status: {exc}")
            await asyncio.sleep(1)

    async def _emit_status_if_changed(self) -> None:
        if not FIRMWARE_UPDATE_STATUS_PATH.exists():
            return

        status_text = FIRMWARE_UPDATE_STATUS_PATH.read_text(encoding="utf-8")
        if status_text == self._last_status:
            return

        self._last_status = status_text
        status = cast(dict[str, object], json.loads(status_text))
        phase = str(status.get("phase", ""))
        message = str(status.get("message", ""))
        percent = int(cast(int | float, status.get("percent", 0)))

        if phase == "completed":
            toast_success(
                identifier=FIRMWARE_UPDATE_TOAST_ID,
                content=ToastContent(message_key="toasts_firmware_update_success"),
                action=None,
            )
            return

        if phase == "failed":
            toast_error(
                identifier=FIRMWARE_UPDATE_TOAST_ID,
                content=ToastContent(
                    message_key="toasts_firmware_install_failed",
                    description_key="toasts_firmware_install_failed_description",
                    description_args={"message": message},
                ),
                action=None,
            )
            return

        if phase == "rolled-back":
            toast_error(
                identifier=FIRMWARE_UPDATE_TOAST_ID,
                content=ToastContent(
                    message_key="toasts_firmware_update_rolled_back",
                    description_key="toasts_firmware_update_rolled_back_description",
                    description_args={"message": message},
                ),
                action=None,
            )
            return

        message_key = _PHASE_MESSAGE_KEYS.get(
            phase, "toasts_firmware_update_installing"
        )
        description_key = _PHASE_DESCRIPTION_KEYS.get(phase)
        toast_loading(
            identifier=FIRMWARE_UPDATE_TOAST_ID,
            content=ToastContent(
                message_key=message_key,
                message_args={"percent": percent},
                description_key=description_key,
            ),
            action=None,
        )

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            method, path, headers = await self._read_request_headers(reader)
            if method == "POST" and path == "/firmware/update":
                await self._handle_update_upload(reader, writer, headers)
                return
            if method == "GET" and path == "/firmware/health":
                await self._handle_health(writer)
                return
            if method == "POST" and path == "/firmware/rollback":
                await self._handle_rollback(writer)
                return
            await self._send_response(writer, 404, "Not found")
        except Exception as exc:
            log_error(f"Firmware update server error: {exc}")
            await self._send_response(writer, 500, str(exc))
        finally:
            writer.close()
            await writer.wait_closed()

    async def _read_request_headers(
        self,
        reader: asyncio.StreamReader,
    ) -> tuple[str, str, dict[str, str]]:
        header_bytes = await reader.readuntil(b"\r\n\r\n")
        if len(header_bytes) > FIRMWARE_UPDATE_MAX_HEADER_BYTES:
            msg = "Firmware update request headers are too large"
            raise ValueError(msg)

        header_text = header_bytes.decode("utf-8")
        lines = header_text.split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        return method, path, headers

    async def _handle_update_upload(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        if self.state.firmware_uploading:
            await self._send_response(
                writer, 409, "Firmware update already in progress"
            )
            return

        self.state.firmware_uploading = True
        try:
            file_name = self._require_safe_file_name(headers)
            content_length = self._require_content_length(headers)
            bundle_path = FIRMWARE_UPDATE_DIR / file_name
            partial_path = bundle_path.with_suffix(f"{bundle_path.suffix}.part")
            self._prepare_staging_paths()
            self._require_free_space(content_length)

            try:
                await self._stream_body(reader, partial_path, content_length)
                _ = partial_path.replace(bundle_path)
                self._write_request(bundle_path)
            except Exception:
                partial_path.unlink(missing_ok=True)
                raise

            toast_loading(
                identifier=FIRMWARE_UPDATE_TOAST_ID,
                content=ToastContent(message_key="toasts_firmware_update_installing"),
                action=None,
            )
            await self._send_response(writer, 202, "Firmware update accepted")
            log_info(f"Firmware update staged at {bundle_path}")
        finally:
            self.state.firmware_uploading = False

    async def _handle_health(self, writer: asyncio.StreamWriter) -> None:
        """Return 200 only when the firmware service is fully alive.

        Used by the on-device rauc-mark-good service to gate slot promotion.
        """
        health = self.state.system_health
        ready = (
            health.imu_healthy and health.pressure_sensor_healthy and health.mcu_healthy
        )
        if ready:
            await self._send_response(writer, 200, "ready")
        else:
            await self._send_response(writer, 503, "not ready")

    async def _handle_rollback(self, writer: asyncio.StreamWriter) -> None:
        """Mark the running slot bad and reboot to revert to the previous slot."""
        proc = await asyncio.create_subprocess_exec(
            FIRMWARE_UPDATE_RAUC_BIN,
            "status",
            "mark-bad",
            "booted",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            log_error(f"rauc mark-bad failed: {err}")
            await self._send_response(writer, 500, f"rauc mark-bad failed: {err}")
            return

        log_info(f"Slot marked bad: {stdout.decode('utf-8', errors='replace').strip()}")
        await self._send_response(writer, 202, "rollback scheduled")

        async def _reboot() -> None:
            await asyncio.sleep(1)
            _ = await asyncio.create_subprocess_exec(
                FIRMWARE_UPDATE_SYSTEMCTL_BIN,
                "reboot",
            )

        task = asyncio.create_task(_reboot())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    @staticmethod
    def _require_safe_file_name(headers: dict[str, str]) -> str:
        file_name = Path(headers.get("x-firmware-file-name", "")).name
        if not file_name.endswith(FIRMWARE_UPDATE_BUNDLE_SUFFIX):
            msg = f"Firmware update file must be a {FIRMWARE_UPDATE_BUNDLE_SUFFIX} artifact"
            raise ValueError(msg)
        return file_name

    @staticmethod
    def _require_content_length(headers: dict[str, str]) -> int:
        content_length = int(headers.get("content-length", "0"))
        if content_length <= 0:
            msg = "Firmware update body is empty"
            raise ValueError(msg)
        return content_length

    @staticmethod
    def _prepare_staging_paths() -> None:
        FIRMWARE_UPDATE_REQUEST_PATH.unlink(missing_ok=True)
        FIRMWARE_UPDATE_STATUS_PATH.unlink(missing_ok=True)
        for pattern in ("*.part", f"*{FIRMWARE_UPDATE_BUNDLE_SUFFIX}"):
            for path in FIRMWARE_UPDATE_DIR.glob(pattern):
                path.unlink(missing_ok=True)

    @staticmethod
    def _require_free_space(content_length: int) -> None:
        disk_usage = shutil.disk_usage(FIRMWARE_UPDATE_DIR)
        required_space = content_length + FIRMWARE_UPDATE_FREE_SPACE_MARGIN_BYTES
        if disk_usage.free < required_space:
            msg = "Not enough free disk space for firmware update upload"
            raise ValueError(msg)

    async def _stream_body(
        self,
        reader: asyncio.StreamReader,
        partial_path: Path,
        content_length: int,
    ) -> None:
        written = 0
        last_percent = -1
        with partial_path.open("wb") as handle:
            while written < content_length:
                chunk = await reader.read(
                    min(FIRMWARE_UPDATE_CHUNK_SIZE, content_length - written)
                )
                if not chunk:
                    msg = "Firmware update upload ended early"
                    raise ValueError(msg)
                _ = handle.write(chunk)
                written += len(chunk)
                percent = int((written / content_length) * 100)
                if percent != last_percent and percent % 5 == 0:
                    last_percent = percent
                    toast_loading(
                        identifier=FIRMWARE_UPDATE_TOAST_ID,
                        content=ToastContent(
                            message_key="toasts_firmware_update_uploading",
                            message_args={"percent": percent},
                        ),
                        action=None,
                    )

    @staticmethod
    def _write_request(bundle_path: Path) -> None:
        request = {"bundlePath": str(bundle_path)}
        _, tmp_name = tempfile.mkstemp(dir=FIRMWARE_UPDATE_DIR, suffix=".json")
        tmp_path = Path(tmp_name)
        _ = tmp_path.write_text(json.dumps(request), encoding="utf-8")
        _ = tmp_path.replace(FIRMWARE_UPDATE_REQUEST_PATH)

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        body: str,
    ) -> None:
        reason = {
            200: "OK",
            202: "Accepted",
            404: "Not Found",
            409: "Conflict",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }.get(status, "OK")
        encoded = body.encode("utf-8")
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Length: {len(encoded)}\r\n"
            "Connection: close\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        )
        writer.write(response.encode("utf-8") + encoded)
        await writer.drain()
