# Cyberfish Firmware

## Raspberry Pi Setup

Connect to the Pi via Ethernet cable. Then SSH into it:

```bash
ssh pi@raspberrypi.local
```

### Setup Networking

#### Install Required Packages

Enter the Raspberry Pi configuration tool:

```bash
sudo raspi-config
```

Now you need to connect the pi to the internet temporarily.

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
static routers=10.69.69.1
static domain_name_servers=8.8.8.8 8.8.4.4
```

#### Configure DHCP Server

Edit the `dnsmasq` configuration file:

```bash
sudo vi /etc/dnsmasq.conf
```

Add these lines:

```
interface=eth0
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
