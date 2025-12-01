import socket, struct
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


def detect_interface():
    """
    Detect a suitable network interface:
    - Prefer interfaces with names like eth*, en*, enp*, ens*
    - Fall back to first non-loopback UP interface with an inet addr
    - Ignore obvious virtual/docker interfaces (veth, docker*, br-*, cni0)
    """
    global host_ip, cidr, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host

    if sys.startswith("linux"):
        # get a compact ip output with addresses on one line per interface
        result = subprocess.check_output(["ip", "-o", "addr"], text=True)
        # lines look like: "2: eth0    inet 172.18.0.2/16 brd 172.18.255.255 scope global eth0\n"
        candidates = []
        for line in result.splitlines():
            # skip loopback
            if "LOOPBACK" in line or " lo " in line:
                continue
            # extract interface name
            m = re.match(r'^\d+:\s+([^:]+)\s', line)
            if not m:
                continue
            name = m.group(1)
            # ignore obvious virtual/docker interfaces
            low = name.lower()
            if low.startswith(("veth", "docker", "br-", "cni0")):
                continue
            # only consider interfaces that have an inet address
            if "inet " not in line:
                continue
            candidates.append(name)

        # prefer ethernet-like predictable names
        for pref in ("eth", "enp", "ens", "en"):
            for c in candidates:
                if c.startswith(pref):
                    interface = c
                    break
            if interface:
                break

        # otherwise pick the first candidate
        if not interface and candidates:
            interface = candidates[0]

        if not interface:
            # as a very last resort, check 'ip a' and pick a non-lo interface name
            result2 = subprocess.check_output(["ip", "a"], text=True)
            interfaces = re.findall(r'^\d+:\s+([\w\d\-\_@]+):', result2, re.MULTILINE)
            for i in interfaces:
                if i.startswith("lo"):
                    continue
                if i.startswith(("veth", "docker", "br-")):
                    continue
                interface = i.split('@')[0] if '@' in i else i
                break

        if not interface:
            raise Exception("[-] No Ethernet interface found")
        print("[+] Detected interface:", interface)

    elif sys.startswith("win") or sys.startswith("nt"):
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -ExpandProperty Name"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        interfaces = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        for i in interfaces:
            u = i.lower()
            if u.startswith(("eth", "en", "wi", "lan")):
                interface = u
                break
        if not interface and interfaces:
            interface = interfaces[0].lower()
        if not interface:
            raise Exception("[-] No Ethernet interface found")


def get_network_info():
    """Get dynamic network information using only socket module and basic assumptions"""
    global host_ip, cidr, interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host

    # Try to get the IP from a socket (this will work even in many container setups)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        host_ip = s.getsockname()[0]
    except Exception:
        # fallback: try to read from ip command for the detected interface
        try:
            if interface:
                out = subprocess.check_output(["ip", "-o", "addr", "show", interface], text=True)
                # find the inet address like: inet 172.18.0.2/16 brd 172.18.255.255
                m = re.search(r'inet\s+([\d\.]+)/(\d+)\s+brd\s+([\d\.]+)', out)
                if m:
                    host_ip = m.group(1)
                    cidr = m.group(2)
                    broadcast_address = m.group(3)
        except Exception:
            pass
    finally:
        s.close()

    if not host_ip:
        raise Exception("[-] Unable to determine host IP")

    # If cidr wasn't filled from ip output, infer from common private ranges
    if not cidr:
        ip_parts = list(map(int, host_ip.split('.')))
        if ip_parts[0] == 10:
            cidr = "8"
            subnet = "255.0.0.0"
        elif ip_parts[0] == 172 and 16 <= ip_parts[1] <= 31:
            cidr = "16"
            subnet = "255.255.0.0"
        elif ip_parts[0] == 192 and ip_parts[1] == 168:
            cidr = "24"
            subnet = "255.255.255.0"
        else:
            cidr = "24"
            subnet = "255.255.255.0"
    else:
        # convert cidr to subnet mask
        mask_int = (0xFFFFFFFF << (32 - int(cidr))) & 0xFFFFFFFF
        subnet = socket.inet_ntoa(struct.pack("!I", mask_int))

    # numeric conversions to compute network and broadcast/gateway
    ip_int = struct.unpack("!I", socket.inet_aton(host_ip))[0]
    subnet_int = struct.unpack("!I", socket.inet_aton(subnet))[0]
    network_int = ip_int & subnet_int
    broadcast_int = network_int | (~subnet_int & 0xFFFFFFFF)
    gateway_int = network_int + 1

    gateway = socket.inet_ntoa(struct.pack("!I", gateway_int))
    broadcast = socket.inet_ntoa(struct.pack("!I", broadcast_int))

    # set globals
    gateway = gateway
    broadcast_address = broadcast

    # return dict
    return {
        "HOST": host_ip,
        "SUBNET": subnet,
        "CIDR": cidr,
        "GATEWAY": gateway,
        "BROADCAST": broadcast
    }



def load_env_vars():
    """Load environment variables from .env file into global variables"""
    global host_ip, cidr,  interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host
    
    load_dotenv()
    
    # Load basic variables
    pwd = os.getenv("PWD", os.getcwd())
    user = os.getenv("USER", getpass.getuser())
    sys = os.getenv("SYSTEM", platform.system().lower())
    interface = os.getenv("INTERFACE", interface)
    host_ip = os.getenv("HOST", "")
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
    # print({
    #     "host": host_ip,
    #     "port": port,
    #     "certi": certi,
    #     "key": key,
    #     "out_dir": out_dir,
    #     "src": src_dir,
    #     "interface": interface,
    #     "system": sys,
    #     "pwd": pwd,
    #     "user": user,
    #     "subnet": subnet,
    #     "gateway": gateway,
    #     "broadcast": broadcast_address,
    #     "cidr": cidr,
    #     "dest_host": dest_host
    # })
    return {
        "host": host_ip,
        "port": port,
        "certi": certi,
        "key": key,
        "out_dir": out_dir,
        "src": src_dir,
        "interface": interface,
        "system": sys,
        "pwd": pwd,
        "user": user,
        "subnet": subnet,
        "gateway": gateway,
        "broadcast": broadcast_address,
        "cidr": cidr,
        "dest_host": dest_host
    }


def update_env():
    global host_ip, cidr,  interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host
    



def write_env():
    global host_ip, cidr,  interface, sys, pwd, user, certi, key, out_dir, src_dir, port, broadcast_address, gateway, subnet, dest_host
    detect_interface()
    ls = os.listdir(pwd)
    if "key.pem" not in ls or "cert.pem" not in ls:
        os.system("""openssl req -x509 -nodes -newkey rsa:2048 -keyout key.pem -out cert.pem  -days 365 -subj "/CN=quic-server.local\"""")
    get_network_info()
    env_vars = {
        "HOST": host_ip,
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
