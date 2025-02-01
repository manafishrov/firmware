# Cyberfish Firmware

## Raspberry Pi Setup

### Flash SD Card

Connect the SD card to your computer and make sure you have the latest version of [Raspberry Pi Imager](https://www.raspberrypi.com/software/) installed.

Choose the Raspberry Pi OS Lite image and flash it to the SD card.

Make sure to have SSH enabled on the Pi and hostname so you can SSH into it the first time for the networking setup. We kept the default raspberrypi hostname and pi as the username.

### Setup Networking

Connect to the Pi via Ethernet cable. Then SSH into it:

```bash
ssh pi@raspberrypi.local
```

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
sudo apt install dnsmasq
```

#### Set the Pi's Static IP

Edit the `dhcpcd.conf` file:

```bash
sudo vi /etc/dhcpcd.conf
```

Add the following lines:

```
interface eth0
static ip_address=10.69.69.69/24
```

#### Configure DHCP Server

Edit the `dnsmasq` configuration file:

```bash
sudo vi /etc/dnsmasq.conf
```

Add these lines:

```
interface=eth0
bind-interfaces
dhcp-range=10.69.69.1,10.69.69.50,12h
```

#### Restart Networking Services**

```bash
sudo systemctl restart dhcpcd
sudo systemctl restart dnsmasq
```

Now, when you plug your Mac/PC into the Raspberry Pi via Ethernet, it **automatically gets an IP in the `10.69.69.x` range**.

You can now use the Pi's IP address to SSH into it:

```bash
ssh pi@10.69.69.69
```

And it should now be possible to connect to it via the app after installing the firmware.

## Development setup

Make sure to have python setup and preferably use a virtual environment.

Install the required packages using the following command:

```bash
pip install -r requirements.txt
```

Test camera on the Raspberry Pi by taking a picture:

```bash
libcamera-jpeg -o test.jpg
```

## License

This project is licensed under the GNU Affero General Public License v3.0 or later - see the [LICENSE](LICENSE) file for details.
