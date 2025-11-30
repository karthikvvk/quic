import ipaddress
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import paramiko
import requests
import getpass
import platform
from scanner import gethostlist
import json
import tkinter as tk
from tkinter import filedialog
import os, threading
from quic_transfer import quic_transfer_file, start_quic_server
import asyncio



app = Flask(__name__)
IS_REMOTE = True
ssh_client = None
HOST_FILE = "host_list.json"
OS_TYPE = ""
REMOTE_USER = ""
CHOOSENIP=""
REMOTE_HOST = ""

def join_path(base, name, os_type):
    sep = "\\" if os_type == "windows" else "/"
    if os_type == "windows" and (":" in name or name.startswith("\\")):
        return name
    if os_type != "windows" and name.startswith("/"):
        return name
    base = base.rstrip("\\/")  
    return base + sep + name


def get_OS_TYPE(REMOTE_HOST=""):
    if not IS_REMOTE:
        return "windows" if platform.system().lower().startswith("win") else "linux"
    try:
        response = requests.post(f"http://{REMOTE_HOST}:5000/osinfo", json={"request": "osinfo"}, timeout=5)
        print("Response from remote host:", response.status_code, response.text)
        if response.status_code == 200:
            data = response.json()
            return {"os": data.get("os", "linux"), "user": data.get("user")}
        else:
            return {"os": "linux", "user": None}
    except:
        print(f"Error contacting remote host")
        return {"os": "linux", "user": None}


def init_ssh():
    global ssh_client
    if ssh_client is not None:
        try:
            ssh_client.close()
        except:
            pass
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASS)
    return ssh_client


def run_remote_command(command):
    ssh = init_ssh()
    stdin, stdout, stderr = ssh.exec_command(command)
    output = stdout.read().decode()
    error = stderr.read().decode()
    exit_status = stdout.channel.recv_exit_status()
    return exit_status, output, error


def load_latest_host():
    global REMOTE_HOST, REMOTE_USER, REMOTE_PASS, OS_TYPE, CHOOSENIP
    try:
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


def check_subnet(ip):
    # Load the default IP from environment variable
    host_ip = os.getenv("DEFAULTIP")
    if not host_ip:
        raise ValueError("DEFAULTIP environment variable not set")

    # Split both IPs into parts
    ip_parts = ip.strip().split('.')
    default_parts = host_ip.strip().split('.')
    ed = ip_parts[-1]
    print(ed, "this is ed")
    if ed == '1' or ed == "200" or ed == "255":
        return False
    # Compare all but the last segment
    return ip_parts[:-1] == default_parts[:-1]



@app.route("/selectdest", methods=["GET"])
def select_destination():
    try:
        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title="Select Local Destination Folder")
        root.destroy()
        if not folder:
            return jsonify({"selected": None}), 200
        return jsonify({"selected": folder}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/lsithost", methods=["GET"])
def lsit_host():
    global CHOOSENIP
    host_list = gethostlist()
    load_dotenv()
    CHOOSENIP = os.getenv("CHOOSENIP", "172.18.0.2")
    result = []
    print(host_list)
    for ip in host_list:
        subck = check_subnet(ip)
        print(subck)
        if subck:
            print("Getting OS info for:", ip)
            res = get_OS_TYPE(ip)
            # print(f"os info for {ip}", res)
            os_type = res.get("os")
            username = res.get("user")
            result.append({"host": ip, "os": os_type, "user": username})

    return jsonify(result)


@app.route("/connect", methods=["GET"])
def connect_host():
    if not load_latest_host():
        return jsonify({"error": "No saved host credentials"}), 400
    return jsonify({
        "host": REMOTE_HOST,
        "user": REMOTE_USER,
        "os": OS_TYPE
    })



@app.route("/osinfo", methods=["POST"])
def osinfo():
    try:
        os_name = platform.system().lower()
        user_name = getpass.getuser()
        print(f"OS Info Requested: OS={os_name}, User={user_name}")
        return jsonify({"os": os_name, "user": user_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500






if __name__ == "__main__":
    # app.run(host="0.0.0.0")
    threading.Thread(target=lambda: asyncio.run(start_quic_server(host="0.0.0.0", port=4443)), daemon=True).start()
    app.run(host="0.0.0.0")



