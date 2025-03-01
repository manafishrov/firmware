# Cyberfish Firmware

## Raspberry Pi Setup

### Flash SD Card

Connect the SD card to your computer and make sure you have the latest version of [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed.

When choosing operating system, select "Raspberry Pi OS (other)" > "Raspberry Pi OS Lite (64-bit)".
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

### Setup motor control

The Pi should already have python installed. You can check the version by running:

```bash
python --version
```

#### Install packages

Make sure the Pi is connected to a Network and install numpy:

```bash
sudo apt install -y python3-numpy python3-websockets
```

TODO: Write instructions for setting up motor control (This probably involves moving over the files)

### Setup streaming

#### Install MediaMTX

First download MediaMTX:

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
