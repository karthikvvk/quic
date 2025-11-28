import ipaddress
import getpass
import os
import platform
import re, subprocess
from dotenv import set_key, load_dotenv


# Global variables
dirs = os.listdir()
pwd = os.getcwd()
user = getpass.getuser()
sys = platform.system().lower()
copyfilepath = os.path.join(pwd, "ipsn.txt")
interface = None
laytodir = "pages"
laytofil = "2_File_Manager.py"
lastip = ""
lastcidr = ''
result = None
cmd = None

# Network-related global variables
network = None
network_address = None
subnet_mask = None
broadcast_address = None
gateway = None
default_ip = None
scanner_ip = None
chosen_ip = None
max_hosts = None

lis = ['.env', '1_Select_Host.py', 'server.py', 'requirement.txtt', 'scanner.py', 'startsetup.py', 'set_static_ip.py']
for i in lis:
    if i in dirs:
        pass
    else:
        print(f"Critical File {i} are not Available!!")
        exit()

if os.path.exists(os.path.join(pwd, laytodir, laytofil)):
    pass
else:
    print(f"Critical File {pwd}/pages/2_File_Manager.py are not Available!!")
    exit()


def update_curr_ipcidr():
    global lastip, lastcidr, result, cmd, interface, sys
    
    if sys.startswith("linux"):
        lastip = None
        lastcidr = None
        block = re.search(rf'{interface}:.*?(?=^\d+:|\Z)', result, re.DOTALL | re.MULTILINE)
        if block:
            m = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)', block.group(0))
            if m:
                lastip = m.group(1)
                lastcidr = m.group(2)
                print("lastip:", lastip, "/", lastcidr)
        # lastcidr = 24
    else:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetIPAddress -InterfaceAlias '{interface}' -AddressFamily IPv4).IPAddress"
        ]
        lastip = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore").strip()
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetIPAddress -InterfaceAlias '{interface}' -AddressFamily IPv4).PrefixLength"
        ]
        lastcidr = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore").strip()
        print("Current system IP:", lastip, "/", lastcidr)


def detect_interface():
    global interface, result, cmd, sys
    
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
        update_curr_ipcidr()
        
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
        update_curr_ipcidr()


def load_env_vars():
    """Load environment variables from .env file into global variables"""
    global lastip, lastcidr, pwd, user, sys, interface, copyfilepath
    global network, network_address, subnet_mask, broadcast_address
    global gateway, default_ip, scanner_ip, chosen_ip, max_hosts
    
    load_dotenv()
    
    # Load basic variables
    pwd = os.getenv("PWD", os.getcwd())
    user = os.getenv("USER", getpass.getuser())
    sys = os.getenv("SYSTEM", platform.system().lower())
    interface = os.getenv("INTERFACE", interface)
    copyfilepath = os.getenv("COPYFILEPATH", copyfilepath)
    
    # Load network variables (but will be overridden by current system values)
    default_ip = os.getenv("DEFAULTIP", "")
    subnet_mask = os.getenv("SUBNET", "")
    gateway = os.getenv("GATEWAY", "")
    broadcast_address = os.getenv("BROADCAST", "")
    scanner_ip = os.getenv("SCANNER", "")
    chosen_ip = os.getenv("CHOOSENIP", "")
    
    print(f"[+] Loaded environment variables from .env")
    return True


def update_env():
    global lastip, lastcidr, pwd, user, sys, interface, copyfilepath
    global network, network_address, subnet_mask, broadcast_address
    global gateway, default_ip, scanner_ip, chosen_ip, max_hosts
    
    # First, load env vars (but IP will be overridden)
    load_env_vars()
    
    # NOW detect interface and get CURRENT system IP - this overrides env values
    detect_interface()
    
    # Ensure CIDR is set
    if not lastcidr:
        lastcidr = '24'
    
    # Calculate network parameters based on CURRENT detected IP and CIDR
    if lastip and lastcidr:
        # Create network object
        network = ipaddress.IPv4Network(f"{lastip}/{lastcidr}", strict=False)
        
        # Calculate network parameters
        network_address = str(network.network_address)
        subnet_mask = str(network.netmask)
        broadcast_address = str(network.broadcast_address)
        
        # Calculate default gateway (typically first usable IP)
        gateway = str(network.network_address + 1)
        
        # Calculate default IP (second usable IP)
        default_ip = str(network.network_address + 2)
        
        # Calculate scanner IP (example: .200 in the network, or last-50 if network is small)
        max_hosts = network.num_addresses - 2  # Exclude network and broadcast
        if max_hosts >= 200:
            scanner_ip = str(network.network_address + 200)
        else:
            scanner_ip = str(network.broadcast_address - 50)
        
        # Calculate chosen IP (example: .10 in the network)
        if max_hosts >= 10:
            chosen_ip = str(network.network_address + 10)
        else:
            chosen_ip = str(network.network_address + 2)
        
        print(f"\nNetwork Configuration:")
        print(f"Current System IP: {lastip}/{lastcidr}")
        print(f"Network: {network}")
        print(f"Default IP: {default_ip}")
        print(f"Subnet Mask: {subnet_mask}")
        print(f"Gateway: {gateway}")
        print(f"Broadcast: {broadcast_address}")
        print(f"Scanner IP: {scanner_ip}")
        print(f"Chosen IP: {chosen_ip}")
    else:
        raise Exception("[-] Could not detect IP address and CIDR")

    # Prepare environment variables
    env_vars = {
        "DEFAULTIP": default_ip,
        "SUBNET": subnet_mask,
        "CIDAR": lastcidr,
        "GATEWAY": gateway,
        "BROADCAST": broadcast_address,
        "SCANNER": scanner_ip,
        "PWD": pwd,
        "USER": user,
        "SYSTEM": sys,
        "INTERFACE": interface,
        "COPYFILEPATH": copyfilepath,
        "CHOOSENIP": chosen_ip,
        "LASTIP": lastip,
        "LASTCIDR": lastcidr,
    }

    env_file = ".env"
    load_dotenv(env_file)
    if not os.path.exists(env_file):
        open(env_file, "a").close()

    for key, value in env_vars.items():
        set_key(env_file, key, str(value))

    print(f"\n[+] Environment variables updated in {env_file}")


if __name__ == "__main__":
    update_env()
    os.system("python " + os.path.join(pwd, "set_static_ip.py"))