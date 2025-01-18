import socket 

#pi_ip = input("Enter the IP address of the Raspberry Pi: ")
pi_ip = "169.254.0.2"

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True: 
    message = input("What to send to RasPi?")

    s.sendto(message.encode(), (pi_ip, 12345))
    print(f"Message sent: {message}")



