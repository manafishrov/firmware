# Firmware

The Manafish firmware is designed to run on a Raspberry Pi 3b with an IMX477
camera module. It provides the firmware for controlling and using the Manafish
ROV.

## Building the SD Image

To build the SD image you need to have `nix` installed on an aarch64-linux
platform or proper emulation support for the aarch64-linux platform. Also add
the caches for the `nixos-raspberrypi` flake to the build system so the build
finishes in a reasonable time:

```sh
nix build .
```

When you have built the image you can list it out with the following command:

```sh
ls -lh result/sd-image
```

This will include the size of the image in the output. The image is compressed
with zstd.

## Flashing

We need to plug in the SD card and find out what the device path is for the
SD card.

On linux:

```sh
lsblk
```

On darwin:

```sh
diskutil list
```

On darwin it is usually `/dev/diskX` where `X` is a number for example
`/dev/disk6` (use `/dev/rdiskX` when flashing for better performance).

### Unmount the SD Card

Before flashing, make sure the SD card is unmounted.

On linux:

```sh
sudo umount /dev/sdX*
```

On darwin:

```sh
diskutil unmountDisk /dev/diskX
```

### Flashing the SD Card

To flash the image to the SD card you can use the following command, make sure
to replace `/dev/XXX` with the correct device path for your SD card:

```sh
zstd -dc result/sd-image/*.zst | sudo dd of=/dev/XXX bs=4M status=progress conv=fsync
```

Flashing the SD card on windows is a little more complicated. It is not possible
to build the image on Windows and the commands will not work. Instead start by
downloading the image you want to use form the release page on GitHub. The
image will be in a `.zst` file format.

Make sure you have 7-Zip installed, and right-click the `sd-image` zst file and
select "Extract Here" to extract the image file.

Next make sure you have Rufus installed, and open it.
Select the SD card from the "Device" dropdown.
Click "Select" and choose the extracted .img file.
Click "Start" to begin flashing the SD card.

## Development Hooks

Install the development dependencies and Git hook once per clone:

```sh
uv sync
uv run pre-commit install
```

> [!NOTE]
> The development shell (`nix develop` or direnv) provides the exact Python
> interpreter the project pins in `pyproject.toml`. If you don't use `nix`
> (for example on Windows), `uv` may fail with an error like
> `No interpreter found for Python ==3.13.12`. Install the pinned interpreter
> first so `uv` can find it:
>
> ```sh
> uv python install 3.13.12
> ```

The pre-commit hook runs Ruff on committed Python files before each commit. To
run the same checks across the repository manually:

```sh
uv run pre-commit run --all-files
```

To update hook versions later:

```sh
uv run pre-commit autoupdate
```

## License

This project is licensed under the GNU Affero General Public License v3.0 or
later - see the [LICENSE](LICENSE) file for details.
