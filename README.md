# Cyberfish Firmware

## Raspberry Pi Setup

### Flash SD Card

Connect the SD card to your computer and make sure you have the latest version of [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed.

When choosing operating system, select "Raspberry Pi OS (other)" > "Raspberry Pi OS Lite (64-bit)".
When asked "Would you like to apply OS customization settings?", select "Edit settings".


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

Now you need to connect the pi to the internet temporarily in the raspi-config.
System Options > Wireless Lan > then enter your wifi credentials.

After that install these packages:

```bash
sudo apt update
sudo apt install dhcpcd5
sudo apt install python3-numpy
sudo apt install python3-gi python3-gst-1.0 gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly
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

##### macOS

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

### Verify that everything is working

First try to SSH into the Pi:

```bash
ssh pi@10.10.10.10
```

If it works you are all good. If not SSH in with the hostname and you can verify what is wrong.

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

Next go ahead and disconnect from the Pi and ping it from your computer to make sure your computer is setup correctly and can find the pi:

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

Now you can SSH and conect to the Pi using the static IP address:

```bash
ssh pi@10.10.10.10
```

## Development setup

The Pi should already have Python3 installed. You can check the version by running:

```bash
python3 --version
```

### Camera

Test camera on the Raspberry Pi by running:

```bash
sudo libcamera-hello
```

To take a picture with the camera, run:

```bash
sudo libcamera-jpeg -o test.jpg
```

> [!IMPORTANT]  
> You have to run the command as root with `sudo` because the camera requires root access.

Move the image to your computer:

```bash
scp pi@cyberfish.local:test.jpg .
```

### Basic camera streaming

For basic camera streaming run the following command on the Pi to stream over TCP:

```bash
sudo libcamera-vid -t 0 --width 1280 --height 720 --framerate 30 --inline --listen -o tcp://10.10.10.11:6900
```

And watch the stream on your computer with:

```bash
ffplay tcp://10.10.10.10:6900
```

This requires `ffmpeg` to be installed on your computer.

### Optimized streaming

For optimized streaming with low latency over UDP we are using gstreamer which needs to be installed on both platforms. This type of stream is more compatible with being embedded into the Tauri app.
Run this on the Pi:

```bash
sudo libcamera-vid -t 0 --width 1280 --height 720 --framerate 30 --codec h264 --bitrate 4000000 -o - | \
gst-launch-1.0 -v fdsrc ! h264parse ! rtph264pay config-interval=1 pt=96 ! \
udpsink host=10.10.10.11 port=6900 sync=false async=false qos=false
```

And to watch the stream on your computer:

```bash
gst-launch-1.0 -v udpsrc port=6900 caps="application/x-rtp, payload=96" ! \
rtph264depay ! queue max-size-buffers=1 leaky=downstream ! avdec_h264 ! \
videoconvert ! autovideosink sync=false
```

From my testing the latency is very low and the stream is very smooth, but some frames may get dropped.

## License

This project is licensed under the GNU Affero General Public License v3.0 or later - see the [LICENSE](LICENSE) file for details.
