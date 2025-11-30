import socket
import struct

def get_network_info():
    """Get dynamic network information using only socket module"""
    
    # Get the default IP by connecting to an external address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to external address (doesn't actually send data)
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
    finally:
        s.close()
    
    # Convert IP to integer for calculations
    ip_int = struct.unpack("!I", socket.inet_aton(host_ip))[0]
    
    # Try to get subnet mask (this is platform-dependent but works in most cases)
    # Assuming common /24 network - we'll detect based on IP class
    ip_parts = list(map(int, host_ip.split('.')))
    
    # Determine subnet based on private IP ranges
    if ip_parts[0] == 10:  # Class A private
        subnet = "255.0.0.0"
        cidr = "8"
    elif ip_parts[0] == 172 and 16 <= ip_parts[1] <= 31:  # Class B private
        subnet = "255.255.0.0"
        cidr = "16"
    elif ip_parts[0] == 192 and ip_parts[1] == 168:  # Class C private
        subnet = "255.255.255.0"
        cidr = "24"
    else:  # Default to /24
        subnet = "255.255.255.0"
        cidr = "24"
    
    # Calculate network address
    subnet_int = struct.unpack("!I", socket.inet_aton(subnet))[0]
    network_int = ip_int & subnet_int
    
    # Calculate broadcast address
    broadcast_int = network_int | (~subnet_int & 0xFFFFFFFF)
    
    # Calculate gateway (typically .1 on the network)
    gateway_int = network_int + 1
    
    # Convert back to IP strings
    gateway = socket.inet_ntoa(struct.pack("!I", gateway_int))
    broadcast = socket.inet_ntoa(struct.pack("!I", broadcast_int))
    
    return {
        "DEFAULTIP": host_ip,
        "SUBNET": subnet,
        "CIDR": cidr,
        "GATEWAY": gateway,
        "BROADCAST": broadcast
    }

# Usage
if __name__ == "__main__":
    info = get_network_info()
    for key, value in info.items():
        print(f"{key}: {value}")