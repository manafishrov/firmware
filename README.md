# Manafish Firmware

To build the SD image you need to have nix installed and proper emulation support for the aarch64-linux platform. Also add the caches for the `nixos-raspberrypi` flake to the build system.

Build the SD image:

```sh
nix build .#pi3
```

or `.#pi4` for Raspberry Pi 4

When you have built the image you can list it out with the following command:

```sh
ls -lh result/sd-image
```

This will include the size of the image in the output. The image is compressed with zstd.

Then we need to plug in the SD card and find out what the device path is for the SD card.
On linux:

```sh
lsblk
```

On darwin:

```sh
diskutil list
```

On linux it is usually `/dev/sdX` where `X` is a letter, for example `/dev/sdb`. On macOS it is usually `/dev/diskX` where `X` is a number for example `/dev/disk6`.

To flash the image to the SD card you can use the following command, make sure to replace `/dev/XXX` with the correct device path for your SD card:

```sh
zstd -dc result/sd-image/*.zst | sudo dd of=/dev/XXX bs=4M status=progress oflag=sync
```

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

   ```bash
   sudo ip addr add 10.10.10.11/24 dev eth0
   ```

   Replace `eth0` with your Ethernet interface name if different.

## License

This project is licensed under the GNU Affero General Public License v3.0 or later - see the [LICENSE](LICENSE) file for details.
