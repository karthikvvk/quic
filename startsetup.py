import socket, struct
import ipaddress
import getpass
import os
import platform
import re, subprocess
from dotenv import set_key, load_dotenv


pwd = os.getcwd()
user = getpass.getuser()
sys = platform.system().lower()

interface = None
subnet = None
broadcast_address = None
gateway = None
host_ip = None
cidr = None
port = 4433
out_dir = pwd
src_dir = pwd
key = os.path.join(pwd, "key.pem")
certi = os.path.join(pwd, "cert.pem")
dest_host = ""


def update_curr_ipcidr():
    global host_ip, cidr, result, cmd, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host    
    if sys.startswith("linux"):
        host_ip = None
        cidr = None
        block = re.search(rf'{interface}:.*?(?=^\d+:|\Z)', result, re.DOTALL | re.MULTILINE)
        if block:
            m = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)', block.group(0))
            if m:
                host_ip = m.group(1)
                cidr = m.group(2)
                print("host_ip:", host_ip, "/", cidr)
        # cidr = 24
    else:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetIPAddress -InterfaceAlias '{interface}' -AddressFamily IPv4).IPAddress"
        ]
        host_ip = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore").strip()
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetIPAddress -InterfaceAlias '{interface}' -AddressFamily IPv4).PrefixLength"
        ]
        cidr = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore").strip()
        print("Current system IP:", host_ip, "/", cidr)


def detect_interface():
    global host_ip, cidr, result, cmd, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host
    
    if sys.startswith("linux"):
        result = subprocess.check_output(["ip", "a"], text=True)
        interfaces = re.findall(r'^\d+:\s+([\w\d\-\_]+):', result, re.MULTILINE)
        interface = None
        for i in interfaces:
            if i.startswith("w"):
                interface = i
                print("the iface: ", interface)
                break
        if not interface:
            raise Exception("[-] No Ethernet interface found")
        
    elif sys.startswith("win") or sys.startswith("nt"):
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-NetAdapter | Select-Object -ExpandProperty Name"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        interfaces = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        for i in interfaces:
            u = i.lower()
            if u.startswith("w"):
                interface = u
                break
        if not interface:
            raise Exception("[-] No Ethernet interface found")



def get_network_info():
    """Get dynamic network information using only socket module"""
    global host_ip, cidr, result, cmd, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host

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



def load_env_vars():
    """Load environment variables from .env file into global variables"""
    global host_ip, cidr, result, cmd, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host
    
    load_dotenv()
    
    # Load basic variables
    pwd = os.getenv("PWD", os.getcwd())
    user = os.getenv("USER", getpass.getuser())
    sys = os.getenv("SYSTEM", platform.system().lower())
    interface = os.getenv("INTERFACE", interface)
    host_ip = os.getenv("DEFAULTIP", "")
    subnet = os.getenv("SUBNET", "")
    gateway = os.getenv("GATEWAY", "")
    broadcast_address = os.getenv("BROADCAST", "")
    cidr = os.getenv("CIDR", "")
    port = int(os.getenv("PORT", "4433"))
    out_dir = os.getenv("OUTDIR", "")
    src_dir = os.getenv("SRCDIR", "")
    certi = os.getenv("CERTI", "")
    key = os.getenv("KEY", "")
    dest_host = os.getenv("DEST_HOST", "")
    
    print(f"[+] Loaded environment variables from .env")
    return host_ip, cidr, result, cmd, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host


def update_env():
    global host_ip, cidr, result, cmd, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host
    



def write_env():
    global host_ip, cidr, result, cmd, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host
    detect_interface()

    get_network_info()
    env_vars = {
        "DEFAULTIP": host_ip,
        "SUBNET": subnet,
        "CIDR": cidr,
        "GATEWAY": gateway,
        "BROADCAST": broadcast_address,
        "PWD": pwd,
        "USER": user,
        "SYSTEM": sys,
        "INTERFACE": interface,
        "PORT": port,
        "OUTDIR": out_dir,
        "SRCDIR": src_dir,
        "CERTI": certi,
        "KEY": key,
        "DEST_HOST": dest_host

    }

    env_file = ".env"
    load_dotenv(env_file)
    if not os.path.exists(env_file):
        open(env_file, "a").close()

    for key, value in env_vars.items():
        set_key(env_file, key, str(value))

    print(f"\n[+] Environment variables updated in {env_file}")


if __name__ == "__main__":
    write_env()
