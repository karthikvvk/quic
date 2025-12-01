from datetime import datetime
from flask import Flask, request, jsonify
import asyncio
import os
import json
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration
import requests
from startsetup import *
from scanner import *
from flask_cors import CORS


app = Flask(__name__)

CHUNK_SIZE = 64 * 1024  # 64KB
ENV_FILE = ".env"
CORS(app, resources={r"/*": {"origins":"*"}})

async def send_command(host, port, cert_verify, command, src=None, dest=None):
    """
    Send command to remote peer via QUIC
    - src: absolute path of source file (for copy/move/delete/create)
    - dest: absolute path of destination directory (for copy/move)
    """
    config = QuicConfiguration(is_client=True, verify_mode=0)
    if cert_verify:
        config.load_verify_locations(cert_verify)

    async with connect(host, port, configuration=config) as client:
        stream_id = client._quic.get_next_available_stream_id(is_unidirectional=False)
        print(f"[+] Sending command: {command}, src: {src}, dest: {dest}")

        # Build header with absolute paths
        header_dict = {"command": command}

        if src:
            header_dict["src"] = src  # Full absolute path

        if dest:
            header_dict["dest"] = dest  # Full absolute destination path

        header = json.dumps(header_dict).encode()
        client._quic.send_stream_data(stream_id, header + b"\n", end_stream=False)
        client.transmit()

        # Send file data for copy/move
        if command in ["copy", "move"] and src:
            if not os.path.exists(src):
                print(f"[!] Source file not found: {src}")
                return
                
            with open(src, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        client._quic.send_stream_data(stream_id, b"", end_stream=True)
                        client.transmit()
                        break
                    client._quic.send_stream_data(stream_id, chunk, end_stream=False)
                    client.transmit()

        elif command in ["create", "delete"]:
            client._quic.send_stream_data(stream_id, b"", end_stream=True)
            client.transmit()

        await asyncio.sleep(0.5)


def check_subnet(ip):
    env = load_env_vars()
    host_ip = env["host"]
    if not host_ip:
        raise ValueError("HOST environment variable not set")

    ip_parts = ip.strip().split('.')
    default_parts = host_ip.strip().split('.')
    ed = ip_parts[-1]
    
    if ed == '1' or ed == "200" or ed == "255":
        return False
    
    return ip_parts[:-1] == default_parts[:-1]


def get_OS_TYPE(REMOTE_HOST=""):
    if not True:
        return "windows" if platform.system().lower().startswith("win") else "linux"
    try:
        response = requests.post(f"http://{REMOTE_HOST}:5000/osinfo", 
                                json={"request": "osinfo"}, timeout=5)
        print("Response from remote host:", response.status_code, response.text)
        if response.status_code == 200:
            data = response.json()
            return {"os": data.get("os", "linux"), "user": data.get("user")}
        else:
            return {"os": "linux", "user": None}
    except:
        print(f"Error contacting remote host")
        return {"os": "linux", "user": None}


@app.route('/copy', methods=['POST'])
def copy_file():
    """
    Copy file TO remote peer
    Body: {
        "src": "/absolute/path/to/local/file",
        "dest": "/absolute/path/to/remote/directory"
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')  # Absolute local file path
        dest = data.get('dest')  # Absolute remote directory path

        if not src:
            return jsonify({"error": "src (source file path) is required"}), 400
        if not dest:
            return jsonify({"error": "dest (destination directory path) is required"}), 400

        # Verify source exists locally
        if not os.path.exists(src):
            return jsonify({"error": f"Source file not found: {src}"}), 404

        env = load_env_vars()
        dest_host = env.get("dest_host") or env.get("dest")
        port = int(env["port"])
        certi = env["certi"]

        if not dest_host:
            return jsonify({"error": "dest_host not configured"}), 500

        print(f"[API] Copy: {src} -> {dest_host}:{dest}")
        asyncio.run(send_command(dest_host, port, certi, "copy", src, dest))
        
        return jsonify({
            "status": "success",
            "message": f"Copied {os.path.basename(src)} to {dest_host}:{dest}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/move', methods=['POST'])
def move_file():
    """
    Move file TO remote peer (copy then delete local)
    Body: {
        "src": "/absolute/path/to/local/file",
        "dest": "/absolute/path/to/remote/directory"
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')
        dest = data.get('dest')

        if not src:
            return jsonify({"error": "src is required"}), 400
        if not dest:
            return jsonify({"error": "dest is required"}), 400

        if not os.path.exists(src):
            return jsonify({"error": f"Source file not found: {src}"}), 404

        env = load_env_vars()
        dest_host = env.get("dest_host") or env.get("dest")
        port = int(env["port"])
        certi = env["certi"]

        if not dest_host:
            return jsonify({"error": "dest_host not configured"}), 500

        print(f"[API] Move: {src} -> {dest_host}:{dest}")
        asyncio.run(send_command(dest_host, port, certi, "move", src, dest))
        
        # Delete local source after successful transfer
        if os.path.exists(src):
            os.remove(src)
            print(f"[+] Deleted local source: {src}")
        
        return jsonify({
            "status": "success",
            "message": f"Moved {os.path.basename(src)} to {dest_host}:{dest}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/delete', methods=['POST'])
def delete_file():
    """
    Delete file on REMOTE peer
    Body: {
        "src": "/absolute/path/to/remote/file"
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')  # Absolute path on remote

        if not src:
            return jsonify({"error": "src is required"}), 400

        env = load_env_vars()
        dest_host = env.get("dest_host") or env.get("dest")
        port = int(env["port"])
        certi = env["certi"]

        if not dest_host:
            return jsonify({"error": "dest_host not configured"}), 500

        print(f"[API] Delete on {dest_host}: {src}")
        asyncio.run(send_command(dest_host, port, certi, "delete", src))
        
        return jsonify({
            "status": "success",
            "message": f"Delete command sent for {src} on {dest_host}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/delete_local', methods=['POST'])
def delete_local_file():
    """
    Delete file on THIS (local) peer
    Body: {
        "src": "/absolute/path/to/local/file"
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')

        if not src:
            return jsonify({"error": "src is required"}), 400

        if not os.path.exists(src):
            return jsonify({"error": f"File not found: {src}"}), 404

        if not os.path.isfile(src):
            return jsonify({"error": f"Not a file: {src}"}), 400

        os.remove(src)
        print(f"[+] Deleted local file: {src}")
        
        return jsonify({
            "status": "success",
            "message": f"Deleted {src}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/create', methods=['POST'])
def create_file():
    """
    Create empty file on REMOTE peer
    Body: {
        "src": "/absolute/path/to/new/file"
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')

        if not src:
            return jsonify({"error": "src is required"}), 400

        env = load_env_vars()
        dest_host = env.get("dest_host") or env.get("dest")
        port = int(env["port"])
        certi = env["certi"]

        if not dest_host:
            return jsonify({"error": "dest_host not configured"}), 500

        print(f"[API] Create on {dest_host}: {src}")
        asyncio.run(send_command(dest_host, port, certi, "create", src))
        
        return jsonify({
            "status": "success",
            "message": f"Create command sent for {src} on {dest_host}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200


@app.route("/listhost", methods=["GET"])
def listhost():
    """List available hosts in subnet"""
    env = load_env_vars()
    host = env["host"]
    
    host_list = gethostlist()
    result = []
    
    print(host_list)
    for ip in host_list:
        subck = check_subnet(ip)
        print(subck)
        if subck:
            res = get_OS_TYPE(ip)
            username = res.get("user")
            result.append({"host": ip, "user": username})

    return jsonify(result)


@app.route("/osinfo", methods=["POST"])
def osinfo():
    """Return OS and user info for this peer"""
    try:
        os_name = platform.system().lower()
        user_name = getpass.getuser()
        print(f"OS Info Requested: OS={os_name}, User={user_name}")
        return jsonify({"os": os_name, "user": user_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/listdir', methods=['POST'])
def list_directory():
    """
    List directory contents on THIS peer
    POST body: {"path": "/absolute/path"}
    Responses (JSON):
      - directory: {"status":"success","type":"directory","files":["a","b",...]}
      - file: {"status":"success","type":"file","info": {"name": "...", "size": 1234, "mtime": "..."}}
      - error: {"status":"error","message":"..."}
    """
    try:
        data = request.get_json()
        path = data.get("path")
        
        if not path:
            return jsonify({"status": "error", "message": "path is required"}), 400

        path = os.path.normpath(path)

        if not os.path.exists(path):
            return jsonify({"status": "error", "message": f"Path does not exist: {path}"}), 404

        if os.path.isfile(path):
            st = os.stat(path)
            info = {
                "name": os.path.basename(path),
                "path": path,
                "size": st.st_size,
                "mtime": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
            }
            return jsonify({"status": "success", "type": "file", "info": info}), 200

        if os.path.isdir(path):
            try:
                items = sorted(os.listdir(path))
            except PermissionError:
                return jsonify({"status": "error", "message": "Permission denied"}), 403
            except Exception as e:
                return jsonify({"status": "error", "message": f"Listing failed: {str(e)}"}), 500

            return jsonify({"status": "success", "type": "directory", "files": items}), 200

        return jsonify({"status": "error", "message": f"Unknown filesystem object: {path}"}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)