import getpass
import os
import subprocess
import platform
import re
import threading
from dotenv import load_dotenv

# Global variables
host_ip = ""
cidr = ""
gateway = ""
subnet = ""
broadcast = ""
interface = ""
system_name = ""
user = ""
pwd = ""
dest_host = ""
file_path = ""


def load_env():
    """Load environment variables from .env file"""
    global host_ip, cidr, gateway, subnet, broadcast, interface, system_name, user, pwd, dest_host
    
    load_dotenv()
    
    # Load from .env with appropriate defaults
    host_ip = os.getenv("HOST", "")
    cidr = os.getenv("CIDR", "24")
    gateway = os.getenv("GATEWAY", "")
    subnet = os.getenv("SUBNET", "255.255.255.0")
    broadcast = os.getenv("BROADCAST", "")
    interface = os.getenv("INTERFACE", "")
    system_name = os.getenv("SYSTEM", platform.system().lower())
    user = os.getenv("USER", getpass.getuser())
    pwd = os.getenv("PWD", os.getcwd())
    dest_host = os.getenv("DEST_HOST", "")
    
    print(f"[+] Loaded scanner environment variables")
    print(f"    Network: {gateway}/{cidr}")
    print(f"    Interface: {interface}")
    print(f"    System: {system_name}")


def checkfile():
    """Ensure the IP list file exists"""
    global file_path
    if not os.path.exists(file_path):
        open(file_path, "w").close()
        print(f"[+] Created {file_path}")


def gethostlist():
    """Main function to scan network and return list of hosts"""
    global file_path, system_name
    
    load_env()
    
    file_path = os.path.join(pwd, "ipsn.txt")
    
    if system_name.startswith("lin"):
        return scanfromlinux()
    elif system_name.startswith("win") or system_name.startswith("nt"):
        return scanfromwin()
    else:
        print(f"[!] Unsupported system: {system_name}")
        return []


def scanfromlinux():
    """Scan network using nmap on Linux"""
    global gateway, cidr, file_path
    print("iam called")
    checkfile()
    
    network = f"{gateway}/{cidr}"
    print(f"[*] Scanning network: {network}")
    
    try:
        result = subprocess.check_output(
            ["nmap", "-sn", "-PR", "-n", network], 
            text=True,
            stderr=subprocess.DEVNULL
        )
        
        unique_ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', result)
        unique_ips = list(set(unique_ips))
        
        print(f"[+] Found {len(unique_ips)} hosts")
        append_host(unique_ips)
        return unique_ips
        
    except subprocess.CalledProcessError as e:
        print(f"[!] nmap error: {e}")
        return []
    except FileNotFoundError:
        print("[!] nmap not found. Please install: sudo apt install nmap")
        return []


def ping_silent(ip):
    """Silent ping for Windows scanning"""
    try:
        subprocess.run(
            ["ping", "-n", "1", "-w", "100", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except:
        pass


def scanfromwin():
    """Scan network using ping + arp on Windows"""
    global gateway, cidr, file_path
    
    checkfile()
    
    # Calculate network range based on gateway and CIDR
    if cidr == "24":
        # For /24 networks, scan the same subnet as gateway
        base = gateway.rsplit('.', 1)[0] + "."
        start, end = 1, 255
    elif cidr == "16":
        # For /16 networks, might need different approach
        parts = gateway.split('.')
        base = f"{parts[0]}.{parts[1]}."
        # For simplicity, scan current /24 subnet only
        base = gateway.rsplit('.', 1)[0] + "."
        start, end = 1, 255
    else:
        # Default to /24 subnet
        base = gateway.rsplit('.', 1)[0] + "."
        start, end = 1, 255
    
    print(f"[*] Scanning network: {base}0/{cidr}")
    print(f"[*] Pinging {end - start} addresses...")
    
    threads = []
    for i in range(start, end + 1):
        ip = base + str(i)
        thr = threading.Thread(target=ping_silent, args=(ip,))
        threads.append(thr)
    
    # Start all threads
    for thr in threads:
        thr.start()
    
    # Wait for all threads to complete
    for thr in threads:
        thr.join()
    
    print("[*] Ping sweep complete, checking ARP cache...")
    
    # Get ARP table
    try:
        result = subprocess.run(
            ["arp", "-a"], 
            capture_output=True, 
            text=True,
            
        )
        output = result.stdout
        
        # Extract all IPs from ARP output
        ips = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', output)
        unique_ips = list(set(ips))
        
        # Filter to only include IPs in our network range
        if cidr == "24":
            unique_ips = [ip for ip in unique_ips if ip.startswith(base)]
        
        print(f"[+] Found {len(unique_ips)} hosts")
        append_host(unique_ips)
        return unique_ips
        
    except subprocess.TimeoutExpired:
        print("[!] ARP command timed out")
        return []
    except Exception as e:
        print(f"[!] Error reading ARP table: {e}")
        return []


def append_host(lis):
    """Append discovered IPs to the host list file"""
    global file_path, pwd
    
    checkfile()
    
    try:
        # Read existing IPs
        with open(file_path, "r") as fh:
            data = fh.readlines()
        
        existing_ips = set(line.strip() for line in data if line.strip())
        
        # Combine with new IPs
        total_ips = existing_ips.union(set(lis))
        
        # Write back sorted list
        with open(file_path, "w") as fh:
            for ip in sorted(total_ips, key=lambda x: [int(p) for p in x.split('.')]):
                fh.write(ip + "\n")
        
        print(f"[+] Updated {file_path} with {len(total_ips)} total hosts")
        
    except Exception as e:
        print(f"[!] Error updating host list: {e}")


# print(gethostlist())