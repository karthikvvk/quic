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
import platform
import getpass


app = Flask(__name__)

CHUNK_SIZE = 64 * 1024  # 64KB
ENV_FILE = ".env"
CORS(app, resources={r"/*": {"origins":"*"}})


async def send_quic_command(host, port, cert_verify, command, src="", dest="", filedata=b""):
    """
    Send a command to remote QUIC server
    - command: "copy", "move", "create", "delete"
    - src: source path (for delete/create operations)
    - dest: destination path (for copy/move operations)
    - filedata: file contents (for copy/move operations)
    """
    config = QuicConfiguration(is_client=True, verify_mode=0)
    if cert_verify:
        config.load_verify_locations(cert_verify)

    try:
        async with connect(host, port, configuration=config) as client:
            stream_id = client._quic.get_next_available_stream_id(is_unidirectional=False)
            
            # Prepare header
            header = json.dumps({
                "command": command,
                "src": src,
                "dest": dest
            }).encode()
            
            print(f"[QUIC] Sending command: {command}, src: {src}, dest: {dest}")
            
            # Send header + delimiter
            client._quic.send_stream_data(stream_id, header + b"\n", end_stream=False)
            client.transmit()
            
            # Send file data if present
            if filedata:
                print(f"[QUIC] Sending {len(filedata)} bytes")
                offset = 0
                while offset < len(filedata):
                    chunk = filedata[offset:offset + CHUNK_SIZE]
                    is_last = (offset + len(chunk)) >= len(filedata)
                    client._quic.send_stream_data(stream_id, chunk, end_stream=is_last)
                    client.transmit()
                    offset += len(chunk)
                    await asyncio.sleep(0.01)  # Small delay between chunks
            else:
                # No file data, close stream
                client._quic.send_stream_data(stream_id, b"", end_stream=True)
                client.transmit()
            
            # Wait for transmission to complete
            await asyncio.sleep(0.5)
            print(f"[QUIC] Command sent successfully")
            
    except Exception as e:
        print(f"[QUIC] Error: {e}")
        raise


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
    try:
        response = requests.post(f"http://{REMOTE_HOST}:5000/osinfo", 
                                json={"request": "osinfo"})
        if response.status_code == 200:
            data = response.json()
            return {"os": data.get("os", "linux"), "user": data.get("user")}
        else:
            return {"os": "linux", "user": None}
    except:
        return {"os": "linux", "user": None}


@app.route('/transfer', methods=['POST'])
def transfer():
    """
    Transfer file to remote peer via QUIC
    Body: {
        "src": "/absolute/path/to/local/file",
        "dest": "/absolute/path/on/remote/where/file/should/be/written"
    }
    """
    try:
        data = request.get_json()
        override_dest_host = data.get("dest_host")
        override_port = data.get("port")

        # Add validation
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        src = data.get('src')
        dest = data.get('dest')

        if not src:
            return jsonify({"error": "src (source file path) is required"}), 400
        if not dest:
            return jsonify({"error": "dest (destination file path) is required"}), 400

        # Verify source exists locally
        if not os.path.exists(src):
            return jsonify({"error": f"Source file not found: {src}"}), 404
        
        # Check if it's actually a file, not a directory
        if not os.path.isfile(src):
            return jsonify({"error": f"Source is not a file: {src}"}), 400

        # Read file data
        try:
            with open(src, "rb") as f:
                filedata = f.read()
        except PermissionError:
            return jsonify({"error": f"Permission denied reading: {src}"}), 403
        except Exception as e:
            return jsonify({"error": f"Failed to read file: {str(e)}"}), 500

        # Load environment variables
        try:
            env = load_env_vars()
        except Exception as e:
            return jsonify({"error": f"Failed to load environment: {str(e)}"}), 500
        
        # Get configuration with better error handling
        dest_host = override_dest_host or env.get("dest_host") or env.get("dest")
        port = int(override_port or env["port"])

        
        certi = env.get("certi")  # This can be None

        print(f"[API] Transfer: {src} -> {dest_host}:{port} -> {dest}")
        print(f"[API] File size: {len(filedata)} bytes")
        print("every variable", src, dest_host, port, certi, dest, override_dest_host, override_port, data)
        # Use QUIC to send file
        try:
            asyncio.run(send_quic_command(
                host=dest_host,
                port=port,
                cert_verify=certi,
                command="copy",
                src=os.path.basename(src),
                dest=dest,
                filedata=filedata
            ))
        except Exception as e:
            return jsonify({"error": f"QUIC transfer failed: {str(e)}"}), 500
        
        return jsonify({
            "status": "success",
            "message": f"Transferred {os.path.basename(src)} to {dest_host}:{dest}",
            "bytes_transferred": len(filedata)
        }), 200

    except Exception as e:
        print(f"[ERROR] Unexpected error in /transfer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500







@app.route('/transferremote', methods=['POST'])
def transfer_remote():
    """
    Proxy transfer request to the actual source host's /transfer endpoint.
    This solves the QUIC stream issue where the stream must originate from the source host.

    Body: {
        "src": "/absolute/path/to/file/on/source/host",
        "dest": "/absolute/path/on/destination/host",
        "source_host": "IP of the host that has the file",
        "dest_host": "IP of the destination host (optional, uses env if not provided)",
        "port": "QUIC port (optional, uses env if not provided)"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        src = data.get('src')
        dest = data.get('dest')
        source_host = data.get('source_host')
        
        if not src:
            return jsonify({"error": "src (source file path) is required"}), 400
        if not dest:
            return jsonify({"error": "dest (destination file path) is required"}), 400
        if not source_host:
            return jsonify({"error": "source_host (IP of host with the file) is required"}), 400
        
        # Prepare the payload for the source host's /transfer endpoint
        transfer_payload = {
            "src": src,
            "dest": dest
        }
        
        # Include optional overrides if provided
        if data.get("dest_host"):
            transfer_payload["dest_host"] = data.get("dest_host")
        if data.get("port"):
            transfer_payload["port"] = data.get("port")
        
        # Call the /transfer endpoint on the source host
        source_url = f"http://{source_host}:5000/transfer"
        
        print(f"[API] TransferRemote: Calling {source_url} with payload: {transfer_payload}")
        
        try:
            response = requests.post(source_url, json=transfer_payload)
            response.raise_for_status()
            
            # Return the response from the source host
            return jsonify(response.json()), response.status_code
            
        except requests.exceptions.Timeout:
            return jsonify({"error": f"Timeout connecting to source host {source_host}"}), 504
        except requests.exceptions.ConnectionError:
            return jsonify({"error": f"Could not connect to source host {source_host}:5000"}), 503
        except requests.exceptions.HTTPError as e:
            return jsonify({"error": f"HTTP error from source host: {str(e)}"}), response.status_code
        except Exception as e:
            return jsonify({"error": f"Failed to call source host: {str(e)}"}), 500

    except Exception as e:
        print(f"[ERROR] Unexpected error in /transferremote: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500




@app.route('/delete_remote', methods=['POST'])
def delete_remote_file():
    """
    Delete file on remote peer via QUIC
    Body: {
        "src": "/absolute/path/to/remote/file"
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
        certi = env.get("certi")

        if not dest_host:
            return jsonify({"error": "dest_host not configured"}), 500

        print(f"[API] Delete remote: {src} on {dest_host}")
        
        # Use QUIC to delete file
        asyncio.run(send_quic_command(
            host=dest_host,
            port=port,
            cert_verify=certi,
            command="delete",
            src=src,
            dest="",
            filedata=b""
        ))
        
        return jsonify({
            "status": "success",
            "message": f"Deleted {src} on {dest_host}"
        }), 200

    except Exception as e:
        print(f"[ERROR] {e}")
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
            result.append({"host": ip, "user": username, "os": res.get("os", "linux")})

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


import os
from datetime import datetime
from flask import request, jsonify

@app.route('/listdir', methods=['POST'])
def list_directory():
    """
    List directory contents on THIS peer
    POST body: {"path": "/absolute/path"}
    - Windows: keep current behavior (list of names)
    - Linux: identify only file or directory
    """
    try:
        data = request.get_json()
        path = data.get("path")
        
        if not path:
            return jsonify({"status": "error", "message": "path is required"}), 400

        # Normalize path
        path = os.path.normpath(path)
        
        # Handle Windows drive letters
        if os.name == 'nt' and len(path) == 2 and path[1] == ':':
            path = path + os.sep

        if not os.path.exists(path):
            return jsonify({"status": "error", "message": f"Path does not exist: {path}"}), 404

        # File response (same as before)
        if os.path.isfile(path):
            st = os.stat(path)
            info = {
                "name": os.path.basename(path),
                "path": path,
                "size": st.st_size,
                "mtime": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
            }
            return jsonify({"status": "success", "type": "file", "info": info}), 200

        # Directory response
        if os.path.isdir(path):
            try:
                items = sorted(os.listdir(path))
            except PermissionError:
                return jsonify({"status": "error", "message": "Permission denied"}), 403
            except Exception as e:
                return jsonify({"status": "error", "message": f"Listing failed: {str(e)}"}), 500

            # Windows → keep original behavior (list of names)
            if os.name == 'nt':
                return jsonify({"status": "success", "type": "directory", "files": items}), 200

            # Linux → return simple file/dir identification
            files_info = []
            for name in items:
                full = os.path.join(path, name)

                if os.path.isdir(full):
                    ftype = "directory"
                elif os.path.isfile(full):
                    ftype = "file"
                else:
                    # treat anything else as file to avoid complexity
                    ftype = "file"

                files_info.append({
                    "name": name,
                    "type": ftype
                })

            return jsonify({"status": "success", "type": "directory", "files": files_info}), 200

        # Unsupported
        return jsonify({"status": "error", "message": f"Unsupported object: {path}"}), 400

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)