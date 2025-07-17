# Manafish Firmware

The Manafish firmware is designed to run on Raspberry Pi devices, specifically the Raspberry Pi 3 and 4. It provides the firmware for controlling and using the Manafish ROV.
For the Raspberry Pico part of the firmware that controls the thrusters see [here](pico/README.md).

## Building the SD Image

To build the SD image you need to have `nix` installed and proper emulation support for the aarch64-linux platform. Also add the caches for the `nixos-raspberrypi` flake to the build system so the build finishes in a reasonable time. Run the command for the specific Pi and camera module you want to use:

```sh
nix build .#pi3-ov5647
nix build .#pi3-imx219
nix build .#pi3-imx477
nix build .#pi4-ov5647
nix build .#pi4-imx219
nix build .#pi4-imx477
```

When you have built the image you can list it out with the following command:

```sh
ls -lh result/sd-image
```

This will include the size of the image in the output. The image is compressed with zstd.

## Flashing the SD Card

We need to plug in the SD card and find out what the device path is for the SD card.

On linux:

```sh
lsblk
```

On darwin:

```sh
diskutil list
```

On linux it is usually `/dev/sdX` where `X` is a letter, for example `/dev/sdb`. On darwin it is usually `/dev/diskX` where `X` is a number for example `/dev/disk6`.

To flash the image to the SD card you can use the following command, make sure to replace `/dev/XXX` with the correct device path for your SD card:

```sh
zstd -dc result/sd-image/*.zst | sudo dd of=/dev/XXX bs=4M status=progress oflag=sync
```

### Windows

Flashing the SD card on windows is a little more complicated. It is not possible to build the image on Windows and the commands will not work. Instead start by downloading the image you want to use form the release page on GitHub. The image will be in a `.zst` file format.

Make sure you have 7-Zip installed, and right-click the `sd-image` zst file and select "Extract Here" to extract the image file.

Next make sure you have Rufus installed, and open it.
Select the SD card from the "Device" dropdown.
Click "Select" and choose the extracted .img file.
Click "Start" to begin flashing the SD card.

## Configure Your Mac/PC's Ethernet Connection

You need to tell your computer how to connect to the Pi without disrupting your regular internet connection.

### MacOS

1. Open System Settings > Network
2. Select your Ethernet connection
3. Click "Details..."
4. Under "Configure IPv4", select "Manually"
5. Set the following:
   - IP Address: 10.10.10.11
   - Subnet Mask: 255.255.255.0
6. Click "OK" and "Apply"

### Windows

1. Open "View Network Connections"
   - You can find this by searching for "View Network Connections" in the Start menu
2. Right-click your Ethernet connection and select "Properties"
3. Select "Internet Protocol Version 4 (TCP/IPv4)" and click "Properties"
4. Select "Use the following IP address" and enter:
   - IP Address: 10.10.10.11
   - Subnet Mask: 255.255.255.0
5. Click "OK" to save

### Linux

1. For Ubuntu/Debian GUI:
   - Open Settings > Network
   - Click the gear icon next to your Ethernet connection
   - Go to IPv4 tab
   - Select "Manual"
   - Add Address: 10.10.10.11
   - Netmask: 255.255.255.0
   - Click "Apply"

2. For command line:

   ```sh
   sudo ip addr add 10.10.10.11/24 dev eth0
   ```

   Replace `eth0` with your Ethernet interface name if different.

## Raspberry Pi

To modify the firmware on the Raspberry Pi, you need to connect to it via SSH. The default username is `pi` and the password is `manafish`. The Pi will be available on port 10.10.10.10 when connected via Ethernet after you have configured your computer's Ethernet connection as described above.

Command to connect via SSH:

```sh
ssh pi@10.10.10.10
```

If you have reflashed the SD card, you may need to delete the known hosts entry for the Pi before connecting:

```sh
ssh-keygen -R 10.10.10.10
```

### WiFi Connection

To connect to a WiFi network on the Pi, use the following commands:

1. List available WiFi networks:

   ```sh
   nmcli device wifi list
   ```

2. Connect to a WiFi network:

   ```sh
   nmcli device wifi connect "NETWORK_NAME" password "PASSWORD"
   ```

3. Check connection status:

   ```sh
   nmcli connection show
   ```

### Firmware Service Management

The Manafish firmware runs as a systemd service. It is set to run automatically on startup, but during development it can be useful to stop/start/restart it. Here are the common commands to manage it:

1. Start the firmware service:

   ```sh
   sudo systemctl start manafish-firmware
   ```

2. Stop the firmware service:

   ```sh
   sudo systemctl stop manafish-firmware
   ```

3. Restart the firmware service:

   ```sh
   sudo systemctl restart manafish-firmware
   ```

4. Check the service status:

   ```sh
   sudo systemctl status manafish-firmware
   ```

5. Disable the service from starting on boot:

   ```sh
   sudo systemctl disable manafish-firmware
   ```

6. View service logs:

  ```sh
  journalctl -u manafish-firmware -f
  ```

## License

This project is licensed under the GNU Affero General Public License v3.0 or later - see the [LICENSE](LICENSE) file for details.
