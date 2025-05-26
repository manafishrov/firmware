# Cyberfish Firmware

To build the SD image you need to have nix installed and proper emulation support for the aarch64-linux platform. Also add the caches for the `nixos-raspberrypi` flake to the build system.

Build the SD image:

```sh
nix build
```

When you have built the image you can list it out with the following command:

```sh
ls -lh result/sd-image
```

This will include the size of the image in the output. The image is compressed with zstd.

Then we need to plug in the SD card and find out what the device path is.
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

## Raspberry Pi Setup (This is all pre NixOS and needs to be removed/updated)

### Flash SD Card

Connect the SD card to your computer and make sure you have the latest version of [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed.

When choosing operating system, select "Raspberry Pi OS (other)" > "Raspberry Pi OS Lite (32-bit)". (We need to use 32-bit for DSHOT to work)
When asked to apply OS customisation settings, select "EDIT SETTINGS".

- Set hostname to `cyberfish.local`
- Set username to `pi`
- Set password to `cyberfish`

Go to "Services" in the top bar and enable SSH with password authentication.

### Setup Networking

Connect to the Pi via Ethernet cable. Then SSH into it via the terminal:

```bash
ssh pi@cyberfish.local
```

> [!WARNING]
> The cyberfish may disconnect at random times when connected via its hostname. This will be fixed after setting up a static IP address.

#### Install Required Packages

Enter the Raspberry Pi configuration tool:

```bash
sudo raspi-config
```

Now you need to connect the Pi to the internet temporarily in the raspi-config.
System Options > Wireless Lan > then enter your wifi credentials.

After that install the dhcpcd5 package:

```bash
sudo apt update
sudo apt install -y dhcpcd5
```

#### Set the Pi's Static IP

Edit the `dhcpcd.conf` file:

```bash
sudo vi /etc/dhcpcd.conf
```

Add the following lines:

```
interface eth0
static ip_address=10.10.10.10/24
```

Then restart the service and the Pi:

```bash
sudo systemctl restart dhcpcd
sudo reboot now
```

#### Configure Your Mac/PC's Ethernet Connection

You need to tell your computer how to connect to the Pi without disrupting your regular internet connection.

##### MacOS

1. Open System Settings > Network
2. Select your Ethernet connection
3. Click "Details..."
4. Under "Configure IPv4", select "Manually"
5. Set the following:
   - IP Address: 10.10.10.11
   - Subnet Mask: 255.255.255.0
6. Click "OK" and "Apply"

##### Windows

1. Open "View Network Connections"
   - You can find this by searching for "View Network Connections" in the Start menu
2. Right-click your Ethernet connection and select "Properties"
3. Select "Internet Protocol Version 4 (TCP/IPv4)" and click "Properties"
4. Select "Use the following IP address" and enter:
   - IP Address: 10.10.10.11
   - Subnet Mask: 255.255.255.0
5. Click "OK" to save

##### Linux

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

#### Verify that network is working

First try to SSH into the Pi:

```bash
ssh pi@10.10.10.10
```

If it works you are all good. If it doesn't work, you need to SSH in with the hostname to find out what's wrong:

```bash
ssh pi@cyberfish.local
```

Verify that the Pi has the correct IP address by running:

```bash
ip addr show eth0
```

It should show the IP address `10.10.10.10/24`. The result may look something like this:

```bash
pi@cyberfish:~ $ ip addr show eth0
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    link/ether b8:27:eb:9a:7f:1c brd ff:ff:ff:ff:ff:ff
    inet 10.10.10.10/24 brd 10.10.10.255 scope global noprefixroute eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::b158:f2c2:d954:b37b/64 scope link noprefixroute
       valid_lft forever preferred_lft forever
```

Next go ahead and disconnect from the Pi and ping it from your computer to make sure your computer is setup correctly and can find the Pi:

```bash
ping 10.10.10.10
```

Your result should look something like this if everything is setup correctly:

```bash
❯ ping 10.10.10.10
PING 10.10.10.10 (10.10.10.10): 56 data bytes
64 bytes from 10.10.10.10: icmp_seq=0 ttl=64 time=0.953 ms
64 bytes from 10.10.10.10: icmp_seq=1 ttl=64 time=1.048 ms
64 bytes from 10.10.10.10: icmp_seq=2 ttl=64 time=1.141 ms
64 bytes from 10.10.10.10: icmp_seq=3 ttl=64 time=1.080 ms
64 bytes from 10.10.10.10: icmp_seq=4 ttl=64 time=1.001 ms
^C
--- 10.10.10.10 ping statistics ---
5 packets transmitted, 5 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 0.953/1.045/1.141/0.065 ms
```

If packets are being lost something is wrong with your setup.

#### Test Camera

Test camera on the Raspberry Pi by running:

```bash
sudo libcamera-hello
```

To take a picture with the camera, run:

```bash
sudo libcamera-jpeg -o test.jpg
```

> [!IMPORTANT]  
> You have to run the commands as root with `sudo` because the camera requires root access.

Use this command on your computer to copy the image from the Pi:

```bash
scp pi@10.10.10.10:test.jpg .
```

To test basic camera streaming run the following command on the Pi to stream over TCP:

```bash
sudo libcamera-vid -t 0 --width 1280 --height 720 --framerate 30 --inline --listen -o tcp://10.10.10.11:6900
```

And watch the stream on your computer with:

```bash
ffplay tcp://10.10.10.10:6900
```

This requires `ffmpeg` to be installed on your computer.

### Setup device controls

The Pi should already have python installed. You can check the version by running:

```bash
python --version
```

#### Install python packages

Make sure the Pi is connected to a Network and install dependencies:

```bash
sudo apt install -y python3-dev python3-setuptools python3-numpy python3-websockets python3-smbus2 i2c-tools
```

#### Build and install the DSHOT package

The motor-dshot-smi.c, rpi_dma_utils.c, and rpi_dma_utils.h files have already been downloaded from the [Marian-Vittek/raspberry-pi-dshot-smi](https://github.com/Marian-Vittek/raspberry-pi-dshot-smi/tree/mai) repository into the dshot directory using:

```bash
wget -P dshot https://raw.githubusercontent.com/Marian-Vittek/raspberry-pi-dshot-smi/main/motor-dshot-smi.c
wget -P dshot https://raw.githubusercontent.com/Marian-Vittek/raspberry-pi-dshot-smi/main/rpi_dma_utils.c
wget -P dshot https://raw.githubusercontent.com/Marian-Vittek/raspberry-pi-dshot-smi/main/rpi_dma_utils.h
```

If there are any updates to the files in the repository, you can download them again using the above commands, but most likely they are fine.
The dshotmodule.c file is a custom python wrapper for the library and the setup.py is for building the python package.

Next, move over the `dshot` directory to the Pi by running this on your computer:

```bash
scp -r dshot/* pi@10.10.10.10:~/dshot
```

Enter the dshot directory on the Pi:

```bash
cd dshot
```

Then build the python package:

```bash
sudo python setup.py build_ext --inplace
```

Install the package to the system:

```bash
sudo python setup.py install
```

And delete the dshot directory on the Pi:

```bash
sudo rm -rf ~/dshot
```

This will make it possible to use the `dshot` module in your python code by running `import dshot`. To look at how the python API looks, you can look at the `dshotmodule.c` file.

#### Flash device controls firmware

Move over the `device_controls` files to the Pi by running this on your computer:

```bash
scp -r device_controls/* pi@10.10.10.10:~/device_controls
```

Just rerun the above command to move over new files to the Pi when you make changes to them (everything has to be kept in the device_controls directory).

Then run the python script to start the device controls:

```bash
python device_controls/main.py
```

#### Run device controls on startup and in the background

Create a systemd service file to run the device controls files on startup:

```bash
sudo vi /etc/systemd/system/device-controls.service
```

Add the following content to the file:

```ini
[Unit]
Description=Device Controls
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/pi/firmware/main.py
WorkingDirectory=/home/pi/firmware
Restart=always
RestartSec=3
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Reload the systemd daemon

```bash
sudo systemctl daemon-reload
```

To start and stop the service during development:

```bash
sudo systemctl start device-controls

sudo systemctl stop device-controls
```

Run this to get continuous logs from the service during testing:

```bash
sudo journalctl -u device-controls -f
```

You can check the status of the service with:

```bash
sudo systemctl status device-controls
```

Enable the service to run automatically on startup using:

```bash
sudo systemctl enable device-controls
```

### Setup streaming

#### Install MediaMTX

First download MediaMTX on the Pi:

```bash
wget https://github.com/bluenviron/mediamtx/releases/download/v1.11.3/mediamtx_v1.11.3_linux_arm64v8.tar.gz
```

Unpack the file and move the binary to the bin directory:

```bash
tar -xvf mediamtx_v1.11.3_linux_arm64v8.tar.gz

# Move to bin
sudo mv mediamtx /usr/local/bin/
```

Delete the files that are not needed:

```bash
rm -rf mediamtx_v1.11.3_linux_arm64v8.tar.gz LICENSE mediamtx.yml
```

Check that MediaMTX is installed:

```bash
mediamtx --version
```

#### Setup configuration

Next we need to setup the configuration file for MediaMTX. We are gonna copy the mediamtx.yml file from this repository to the correct location.

First copy the file to the Pi by running this on your computer:

```bash
scp camera_stream/mediamtx.yml pi@10.10.10.10:~/
```

Create the directory for the configuration file on the Pi and move it to the correct location:

```bash
sudo mkdir /etc/mediamtx

# Move the file to the correct location on the Pi
sudo mv mediamtx.yml /etc/mediamtx/
```

The stream is setup so it will automatically start when connected to from the app and shut down when disconnected.

#### Run MediaMTX service in the background

Now we need to make sure the MediaMTX service is always running in the background when the Pi is turned on.

Create a systemd service file to run MediaMTX on startup:

```bash
sudo vi /etc/systemd/system/mediamtx.service
```

Add the following content to the file:

```ini
[Unit]
Description=MediaMTX
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mediamtx
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
# Reload the systemd daemon
sudo systemctl daemon-reload

# Enable the service on startup
sudo systemctl enable mediamtx

# Start the service now
sudo systemctl start mediamtx
```

You can check the status of the service with:

```bash
sudo systemctl status mediamtx
```

#### Test the stream

To test the stream just open this URL in your browser:
[http://10.10.10.10:8889/cam](http://10.10.10.10:8889/cam)

> [!IMPORTANT]  
> You need to be connected to the Pi to access the stream.

## License

This project is licensed under the GNU Affero General Public License v3.0 or later - see the [LICENSE](LICENSE) file for details.
