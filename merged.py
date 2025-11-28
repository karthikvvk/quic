"""
Merged Flask + QUIC server
Combines the new server's QUIC client endpoints (/copy, /move, /create, /delete, /health)
with the old server's host discovery / UI helpers (/selectdest, /lsithost, /connect, /osinfo)
and background QUIC server starter.

Drop this file into your project, ensure the helper modules (quic_transfer, scanner, helper)
and .env / host_list.json exist. Install dependencies: flask, python-dotenv, aioquic, paramiko, requests.
"""

import os
import json
import threading
import asyncio
import platform
import getpass
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, jsonify

# QUIC client/server helpers (from your project)
# quic_transfer should expose: start_quic_server, quic_transfer_file (optional)
# scanner should expose: gethostlist
try:
    from quic_transfer import start_quic_server
except Exception:
    start_quic_server = None

try:
    from scanner import gethostlist
except Exception:
    gethostlist = lambda: []

# New QUIC client bits
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

# Optional paramiko for SSH remote-exec functionality used by old server
try:
    import paramiko
except Exception:
    paramiko = None

# Optional tkinter for select destination dialog (old behavior)
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None

app = Flask(__name__)

# ---- Configuration / Globals ----
CHUNK_SIZE = 64 * 1024  # 64KiB
HOST_FILE = "host_list.json"
IS_REMOTE = True
ssh_client = None
REMOTE_USER = ""
REMOTE_PASS = ""
REMOTE_HOST = ""
OS_TYPE = ""
CHOOSENIP = ""

# ---- Utility functions from old server ----

def join_path(base: str, name: str, os_type: str) -> str:
    sep = "\\" if os_type == "windows" else "/"
    # if absolute windows path or already has drive, return name
    if os_type == "windows" and (":" in name or name.startswith("\\")):
        return name
    if os_type != "windows" and name.startswith("/"):
        return name
    base = base.rstrip("\\/")
    return base + sep + name


def load_latest_host():
    global REMOTE_HOST, REMOTE_USER, REMOTE_PASS, OS_TYPE, CHOOSENIP
    try:
        if not os.path.exists(HOST_FILE):
            return False
        with open(HOST_FILE, "r") as f:
            data = json.load(f)
        if not data:
            return False
        latest = data[-1]
        REMOTE_HOST = latest.get("ip")
        REMOTE_USER = latest.get("username")
        REMOTE_PASS = latest.get("password")
        OS_TYPE = latest.get("os_type", "linux")
        load_dotenv()
        CHOOSENIP = os.getenv("CHOOSENIP", "172.18.0.2")
        return True
    except Exception as e:
        print(f"Error reading host file: {e}")
        return False


def check_subnet(ip: str) -> bool:
    # Load the default IP from environment variable
    default_ip = os.getenv("DEFAULTIP")
    if not default_ip:
        raise ValueError("DEFAULTIP environment variable not set")

    ip_parts = ip.strip().split('.')
    default_parts = default_ip.strip().split('.')
    ed = ip_parts[-1]
    # avoid special hosts
    if ed in ('1', '200', '255'):
        return False
    return ip_parts[:-1] == default_parts[:-1]


def get_OS_TYPE(REMOTE_HOST=""):
    if not IS_REMOTE:
        return "windows" if platform.system().lower().startswith("win") else "linux"
    try:
        response = requests.post(f"http://{REMOTE_HOST}:5000/osinfo", json={"request": "osinfo"}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {"os": data.get("os", "linux"), "user": data.get("user")}
        else:
            return {"os": "linux", "user": None}
    except Exception:
        return {"os": "linux", "user": None}

# SSH helpers

def init_ssh():
    global ssh_client
    if paramiko is None:
        raise RuntimeError("paramiko not installed")
    if ssh_client is not None:
        try:
            ssh_client.close()
        except Exception:
            pass
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASS)
    return ssh_client


def run_remote_command(command: str):
    ssh = init_ssh()
    stdin, stdout, stderr = ssh.exec_command(command)
    output = stdout.read().decode()
    error = stderr.read().decode()
    exit_status = stdout.channel.recv_exit_status()
    return exit_status, output, error

# ---- Environment reader for new endpoints (read_env_file) ----

def read_env_file(env_path: str = ".env") -> dict:
    load_dotenv(env_path)
    env = {
        "host": os.getenv("HOST", "127.0.0.1"),
        "port": int(os.getenv("PORT", "4443")),
        "certi": os.getenv("CERT_FILE", ""),
        "out_dir": os.getenv("OUT_DIR", "/tmp")
    }
    return env

# ---- New QUIC client send_command (adapted) ----
async def send_command(host, port, cert_verify, command, src=None, dest=None):
    # verify_mode 0 -> no verify; if cert_verify provided, load CA
    config = QuicConfiguration(is_client=True, verify_mode=0)
    if cert_verify:
        # if cert_verify is a path, attempt to load
        try:
            config.load_verify_locations(cert_verify)
        except Exception:
            pass

    async with connect(host, port, configuration=config) as client:
        # use high-level stream API via connection
        stream_id = client._quic.get_next_available_stream_id(is_unidirectional=False)
        print(f"[+] sending command on stream {stream_id}")

        header_dict = {"command": command}
        if src:
            header_dict["src"] = os.path.normpath(src)

        if command in ["copy", "move"]:
            header_dict["dest"] = os.path.normpath(dest) if dest else None

        header = json.dumps(header_dict).encode()
        client._quic.send_stream_data(stream_id, header + b"\n", end_stream=False)
        client.transmit()

        # send file data if required
        if command in ["copy", "move"] and src:
            # src might be a local path or a file in a staging directory
            with open(src, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        client._quic.send_stream_data(stream_id, b"", end_stream=True)
                        client.transmit()
                        break
                    client._quic.send_stream_data(stream_id, chunk, end_stream=False)
                    client.transmit()
        else:
            client._quic.send_stream_data(stream_id, b"", end_stream=True)
            client.transmit()

        # small wait to ensure packets are sent
        await asyncio.sleep(0.2)

# ---- Flask endpoints (new + old) ----
@app.route('/copy', methods=['POST'])
def copy_file():
    try:
        data = request.get_json()
        src = data.get('src')
        print(f"Received copy request: {data}")
        dest = data.get('dest')
        if not src:
            return jsonify({"error": "src is required"}), 400
        env = read_env_file()
        host, port, certi, out_dir = env["host"], env["port"], env["certi"], env["out_dir"]
        dest = dest or out_dir
        asyncio.run(send_command(host, port, certi, "copy", src, dest))
        return jsonify({"status": "success", "message": f"Copy command sent for {src} to {dest}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/move', methods=['POST'])
def move_file():
    try:
        data = request.get_json()
        src = data.get('src')
        dest = data.get('dest')
        if not src:
            return jsonify({"error": "src is required"}), 400
        env = read_env_file()
        host, port, certi, out_dir = env["host"], env["port"], env["certi"], env["out_dir"]
        dest = dest or out_dir
        asyncio.run(send_command(host, port, certi, "move", src, dest))
        return jsonify({"status": "success", "message": f"Move command sent for {src} to {dest}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/create', methods=['POST'])
def create_file():
    try:
        data = request.get_json()
        src = data.get('src')
        if not src:
            return jsonify({"error": "src is required"}), 400
        env = read_env_file()
        host, port, certi = env["host"], env["port"], env["certi"]
        asyncio.run(send_command(host, port, certi, "create", src))
        return jsonify({"status": "success", "message": f"Create command sent for {src}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/delete', methods=['POST'])
def delete_file():
    try:
        data = request.get_json()
        src = data.get('src')
        if not src:
            return jsonify({"error": "src is required"}), 400
        env = read_env_file()
        host, port, certi = env["host"], env["port"], env["certi"]
        asyncio.run(send_command(host, port, certi, "delete", src))
        return jsonify({"status": "success", "message": f"Delete command sent for {src}"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

# ---- Old server endpoints ----
@app.route('/selectdest', methods=['GET'])
def select_destination():
    try:
        if filedialog is None:
            return jsonify({"error": "tkinter not available on this environment"}), 500
        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title="Select Local Destination Folder")
        root.destroy()
        if not folder:
            return jsonify({"selected": None}), 200
        return jsonify({"selected": folder}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/lsithost', methods=['GET'])
def lsit_host():
    global CHOOSENIP
    host_list = gethostlist()
    load_dotenv()
    CHOOSENIP = os.getenv("CHOOSENIP", "172.18.0.2")
    result = []
    for ip in host_list:
        try:
            subck = check_subnet(ip)
        except Exception:
            subck = False
        if subck:
            res = get_OS_TYPE(ip)
            os_type = res.get('os')
            username = res.get('user')
            result.append({"host": ip, "os": os_type, "user": username})
    return jsonify(result)


@app.route('/connect', methods=['GET'])
def connect_host():
    if not load_latest_host():
        return jsonify({"error": "No saved host credentials"}), 400
    return jsonify({"host": REMOTE_HOST, "user": REMOTE_USER, "os": OS_TYPE})


@app.route('/osinfo', methods=['POST'])
def osinfo():
    try:
        os_name = platform.system().lower()
        user_name = getpass.getuser()
        return jsonify({"os": os_name, "user": user_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---- Server startup ----
if __name__ == '__main__':
    # Start QUIC server in background if available
    if start_quic_server is not None:
        print("Starting QUIC server in background thread (if provided by quic_transfer)")
        threading.Thread(target=lambda: asyncio.run(start_quic_server(host='0.0.0.0', port=4443)), daemon=True).start()
    else:
        print("quic_transfer.start_quic_server not available. Skipping QUIC server start.")

    # Run Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)
