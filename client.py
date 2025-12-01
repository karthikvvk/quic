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
CORS(app) 

async def send_command(host, port, cert_verify, command, src=None, dest=None):
    config = QuicConfiguration(is_client=True, verify_mode=0)
    if cert_verify:
        config.load_verify_locations(cert_verify)

    async with connect(host, port, configuration=config) as client:
        stream_id = client._quic.get_next_available_stream_id(is_unidirectional=False)
        print(f"[+] sending command on stream {stream_id}")

        # Build header with standardized fields
        header_dict = {"command": command}

        if src:
            # Send exactly as provided - no basename, no normalization
            header_dict["src"] = src

        if command in ["copy", "move"] and dest:
            # Send exactly as provided - no normalization
            header_dict["dest"] = dest

        header = json.dumps(header_dict).encode()
        client._quic.send_stream_data(stream_id, header + b"\n", end_stream=False)
        client.transmit()

        # Copy/Move stream file data (upload + delete semantics for move)
        if command in ["copy", "move"] and src:
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
            # No file data; just header
            client._quic.send_stream_data(stream_id, b"", end_stream=True)
            client.transmit()

        await asyncio.sleep(0.5)



def check_subnet(ip):
    # Load the default IP from environment variable
    env = load_env_vars()
    host_ip= (
        env["host"]
    )
    if not host_ip:
        raise ValueError("HOST environment variable not set")

    # Split both IPs into parts
    ip_parts = ip.strip().split('.')
    default_parts = host_ip.strip().split('.')
    ed = ip_parts[-1]
    print(ed, "this is ed")
    if ed == '1' or ed == "200" or ed == "255":
        return False
    # Compare all but the last segment
    return ip_parts[:-1] == default_parts[:-1]




def get_OS_TYPE(REMOTE_HOST=""):
    if not True:
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





@app.route('/copy', methods=['POST'])
def copy_file():
    """
    Copy operation endpoint
    POST body: {
        "src": "filename.txt",
        "dest": "/path/to/destination"  (optional, uses env default if not provided)
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')
        dest = data.get('dest')

        if not src:
            return jsonify({"error": "src is required"}), 400

        env = load_env_vars()
        host, port, certi, out_dir = (
            env["host"],
            env["port"],
            env["certi"],
            env["out_dir"]
        )

        dest = dest or out_dir

        asyncio.run(send_command(host, port, certi, "copy", src, dest))
        
        return jsonify({
            "status": "success",
            "message": f"Copy command sent for {src} to {dest}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/move', methods=['POST'])
def move_file():
    """
    Move operation endpoint
    POST body: {
        "src": "filename.txt",
        "dest": "/path/to/destination"  (optional, uses env default if not provided)
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')
        dest = data.get('dest')

        if not src:
            return jsonify({"error": "src is required"}), 400

        env = load_env_vars()
        host, port, certi, out_dir = (
            env["host"],
            env["port"],
            env["certi"],
            env["out_dir"]
        )

        dest = dest or out_dir

        asyncio.run(send_command(host, port, certi, "move", src, dest))
        
        return jsonify({
            "status": "success",
            "message": f"Move command sent for {src} to {dest}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/create', methods=['POST'])
def create_file():
    """
    Create operation endpoint
    POST body: {
        "src": "filename.txt"
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')

        if not src:
            return jsonify({"error": "src is required"}), 400

        env = load_env_vars()
        host, port, certi = (
            env["host"],
            env["port"],
            env["certi"]
        )

        asyncio.run(send_command(host, port, certi, "create", src))
        
        return jsonify({
            "status": "success",
            "message": f"Create command sent for {src}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/delete', methods=['POST'])
def delete_file():
    """
    Delete operation endpoint
    POST body: {
        "src": "filename.txt"
    }
    """
    try:
        data = request.get_json()
        src = data.get('src')

        if not src:
            return jsonify({"error": "src is required"}), 400

        env = load_env_vars()
        host, port, certi = (
            env["host"],
            env["port"],
            env["certi"]
        )

        asyncio.run(send_command(host, port, certi, "delete", src))
        
        return jsonify({
            "status": "success",
            "message": f"Delete command sent for {src}"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

@app.route("/lsithost", methods=["GET"])
def listhost():
    env = load_env_vars()
    host, port, certi = (
        env["host"],
        env["user"],
        env["certi"]
    )
    host_list = gethostlist()
    # load_dotenv()
    # CHOOSENIP = host

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
    POST body: {"cdir": "/path/to/check"}
    Responses (JSON):
      - directory: {"status":"success","type":"directory","files":["a","b",...]}
      - file:      {"status":"success","type":"file","info": {"name": "...", "size": 1234, "mtime": "..."}}
      - error:     {"status":"error","message":"..."}
    """
    try:
        data = request.get_json() or {}
        path = data.get("cdir")
        if not path:
            return jsonify({"status": "error", "message": "cdir is required"}), 400

        # normalize the path (but keep absolute paths if user provided them)
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

        # fallback: unknown type
        return jsonify({"status": "error", "message": f"Unknown filesystem object: {path}"}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)