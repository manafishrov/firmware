# Firmware

The Manafish firmware is designed to run on a Raspberry Pi 3b with an IMX477
camera module. It provides the firmware for controlling and using the Manafish
ROV.

## Current reporting compatibility

Current above idle comes from MCU telemetry type 9: signed int32 milliamps for
two shared-sensor boards, using channel IDs 0 and 4. Type 10 carries each idle
baseline for diagnostics; type 3 remains the unchanged raw whole-amp reading.
A value of -1 means unavailable. The Pi sums both fresh corrected board values
and returns `currentDraw: null` when either is missing or stale, or when MCU
health, protocol, or flashing state makes the measurement unavailable. There
is no fallback to raw current and no second offset correction.

The old current-sensor topology setting is ignored on configuration import and
no longer saved or sent. The supported estimator layout is two four-in-one
boards, not individual per-motor sensors. Auto-zero estimates incremental current
above idle; it does not validate the sensor gain or provide electrical protection.
Raw current, corrected current, baseline, and freshness remain in diagnostics.

The app must accept nullable/fractional `currentDraw` before installing this Pi
version. Install the AM32 raw-current restoration and product input policy on
all eight ESCs using the old Pico first, then deploy the new Pico through an
updated Pi bundle. Pi auto-flashing cannot enforce that ESC-first sequence.
Without new MCU reports, current remains unavailable. This release bundles
AM32 v2.21.0-rc.3 and Pico/Pico 2 v1.0.3-rc.7. Do not install this bundle before
updating all eight ESCs with the old Pico; use a separate ESC-first staging step.

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

## Ethernet Connections

The ROV uses `10.10.10.10/24` by default. Connect a computer, phone, or tablet
to its Ethernet port and use that address in the app. The DHCP server assigns
clients an address from the same `/24` subnet without changing the ROV's own
static address.

Android phones and tablets can connect through a USB-C Ethernet adapter without
manual network configuration. Android requires router and DNS fields before it
considers an Ethernet link usable, so the ROV supplies placeholder values only
to clients identifying themselves as Android. The ROV does not provide DNS or
forward internet traffic; the device can therefore keep using Wi-Fi for normal
internet access. An Android "no internet" indication for the Ethernet link is
expected.

Desktop clients receive an address but no default route or DNS server, so the
tether does not replace their existing internet connection. A manual address in
the same subnet, such as `10.10.10.100/24`, also works.

If the ROV address is changed in the app, its DHCP pool follows the selected
`/24` subnet automatically. Reconnect the Ethernet adapter if a client retains
an old lease after that change.

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
