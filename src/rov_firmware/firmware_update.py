"""HTTP firmware update upload server."""

import asyncio
import json
from pathlib import Path
import shutil
import tempfile
from typing import cast

from .constants import (
    FIRMWARE_UPDATE_CHUNK_SIZE,
    FIRMWARE_UPDATE_DIR,
    FIRMWARE_UPDATE_FREE_SPACE_MARGIN_BYTES,
    FIRMWARE_UPDATE_MAX_HEADER_BYTES,
    FIRMWARE_UPDATE_NIX_SYSTEM_PATH_RE,
    FIRMWARE_UPDATE_PORT,
    FIRMWARE_UPDATE_REQUEST_PATH,
    FIRMWARE_UPDATE_STATUS_PATH,
    FIRMWARE_UPDATE_TOAST_ID,
)
from .log import log_error, log_info, log_warn
from .models.toast import ToastContent
from .rov_state import RovState
from .toast import toast_error, toast_loading, toast_success


class HttpUpdateServer:
    """Small HTTP server for staging signed firmware closure uploads."""

    def __init__(self, state: RovState) -> None:
        """Initialize the update upload server."""
        self.state: RovState = state
        self.server: asyncio.Server | None = None
        self._last_status: str | None = None

    async def initialize(self) -> None:
        """Start the HTTP update upload server."""
        FIRMWARE_UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        self.server = await asyncio.start_server(
            self._handle_client,
            self.state.rov_config.ip_address,
            FIRMWARE_UPDATE_PORT,
        )
        log_info(
            f"Firmware update HTTP server started on {self.state.rov_config.ip_address}:{FIRMWARE_UPDATE_PORT}"
        )

    async def wait_closed(self) -> None:
        """Wait for the HTTP server to close."""
        if self.server:
            await self.server.serve_forever()

    async def watch_status_loop(self) -> None:
        """Forward root installer status changes to the app toast."""
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
        status = cast(dict[str, object], json.loads(status_text))
        phase = str(status.get("phase", ""))
        message = str(status.get("message", ""))
        percent = int(cast(int | float, status.get("percent", 0)))
        is_terminal_phase = phase in {"completed", "failed"}

        if status_text == self._last_status and is_terminal_phase:
            return

        self._last_status = status_text

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

        message_key = (
            "toasts_firmware_update_flashing_mcu"
            if phase == "activated"
            else "toasts_firmware_update_installing"
        )
        toast_loading(
            identifier=FIRMWARE_UPDATE_TOAST_ID,
            content=ToastContent(
                message_key=message_key,
                message_args={"percent": percent},
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
            if method != "POST" or path != "/firmware/update":
                await self._send_response(writer, 404, "Not found")
                return

            await self._handle_update_upload(reader, writer, headers)
        except Exception as exc:
            log_error(f"Firmware update upload failed: {exc}")
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
            system_path = self._require_system_path(headers)
            signature = self._require_signature(headers)
            content_length = self._require_content_length(headers)
            closure_path = FIRMWARE_UPDATE_DIR / file_name
            partial_path = closure_path.with_suffix(f"{closure_path.suffix}.part")
            self._prepare_staging_paths()
            self._require_free_space(content_length)

            try:
                await self._stream_body(reader, partial_path, content_length)
                _ = partial_path.replace(closure_path)
                signature_path = Path(f"{closure_path}.minisig")
                _ = signature_path.write_text(signature, encoding="utf-8")
                self._write_request(closure_path, signature_path, system_path)
            except Exception:
                partial_path.unlink(missing_ok=True)
                raise
            toast_loading(
                identifier=FIRMWARE_UPDATE_TOAST_ID,
                content=ToastContent(message_key="toasts_firmware_update_installing"),
                action=None,
            )
            await self._send_response(writer, 202, "Firmware update accepted")
            log_info(f"Firmware update staged at {closure_path}")
        finally:
            self.state.firmware_uploading = False

    def _require_safe_file_name(self, headers: dict[str, str]) -> str:
        file_name = Path(headers.get("x-firmware-file-name", "")).name
        if not file_name.endswith(".closure.zst"):
            msg = "Firmware update file must be a .closure.zst artifact"
            raise ValueError(msg)
        return file_name

    def _require_system_path(self, headers: dict[str, str]) -> str:
        system_path = headers.get("x-firmware-system-path", "")
        if not FIRMWARE_UPDATE_NIX_SYSTEM_PATH_RE.match(system_path):
            msg = "Firmware update system path is invalid"
            raise ValueError(msg)
        return system_path

    def _require_signature(self, headers: dict[str, str]) -> str:
        signature = headers.get("x-firmware-signature", "").replace("\\n", "\n")
        if "minisign" not in signature or len(signature.strip()) == 0:
            msg = "Firmware update signature is invalid"
            raise ValueError(msg)
        return signature

    def _require_content_length(self, headers: dict[str, str]) -> int:
        content_length = int(headers.get("content-length", "0"))
        if content_length <= 0:
            msg = "Firmware update body is empty"
            raise ValueError(msg)
        return content_length

    @staticmethod
    def _prepare_staging_paths() -> None:
        FIRMWARE_UPDATE_REQUEST_PATH.unlink(missing_ok=True)
        for pattern in ("*.part", "*.closure.zst", "*.closure.zst.minisig"):
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

    def _write_request(
        self,
        closure_path: Path,
        signature_path: Path,
        system_path: str,
    ) -> None:
        request = {
            "closurePath": str(closure_path),
            "signaturePath": str(signature_path),
            "systemPath": system_path,
        }
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
            202: "Accepted",
            404: "Not Found",
            409: "Conflict",
            500: "Internal Server Error",
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
