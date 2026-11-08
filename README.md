# Manafish Firmware

NixOS image and Python service for the Raspberry Pi 3B and IMX477 camera in the
Manafish ROV.

## Build the SD image

Building needs Nix on aarch64-linux, or emulation for it, with the
`nixos-raspberrypi` caches configured:

```sh
nix build .
```

The zstd-compressed image is written to `result/sd-image/`. Prebuilt images are
on the [releases page](https://github.com/manafishrov/firmware/releases).

## Flash

Find the SD card with `lsblk` (Linux) or `diskutil list` (macOS), unmount it,
and write the image:

```sh
zstd -dc result/sd-image/*.zst | sudo dd of=/dev/XXX bs=4M status=progress conv=fsync
```

On Windows, extract the `.zst` with 7-Zip and write the `.img` with Rufus.

## Connect

The ROV uses `10.10.10.10` and gives out addresses over DHCP on its Ethernet
port. Connect a computer, or a phone through a USB-C Ethernet adapter, and enter
that address in the app.

## Development

```sh
uv sync
uv run pre-commit install
```

`nix develop` provides the Python version pinned in `pyproject.toml`. Without
Nix, install it first with `uv python install <version>`.

## License

[AGPL-3.0-or-later](LICENSE)
