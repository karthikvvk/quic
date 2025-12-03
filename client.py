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
                                json={"request": "osinfo"}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {"os": data.get("os", "linux"), "user": data.get("user")}
        else:
            return {"os": "linux", "user": None}
    except:
        return {"os": "linux", "user": None}



# @app.route('/transfer_from_remote', methods=['POST'])
# def transfer_from_remote():
#     """
#     Transfer file FROM remote peer TO local via QUIC
#     Body: {
#         "src": "/absolute/path/on/remote",
#         "dest": "/absolute/path/to/local/destination"
#     }
#     """
#     try:
#         data = request.get_json()
#         src = data.get('src')
#         dest = data.get('dest')

#         if not src:
#             return jsonify({"error": "src (remote source path) is required"}), 400
#         if not dest:
#             return jsonify({"error": "dest (local destination path) is required"}), 400

#         env = load_env_vars()
#         dest_host = env.get("dest_host") or env.get("dest")
#         port = int(env["port"])
#         certi = env.get("certi")

#         if not dest_host:
#             return jsonify({"error": "dest_host not configured"}), 500

#         print(f"[API] Transfer from remote: {dest_host}:{src} -> {dest}")
        
#         # Use QUIC to request file from remote (you'll need to implement "fetch" command)
#         asyncio.run(send_quic_command(
#             host=dest_host,
#             port=port,
#             cert_verify=certi,
#             command="fetch",  # New command to GET file from remote
#             src=src,
#             dest=dest,
#             filedata=b""
#         ))
        
#         return jsonify({
#             "status": "success",
#             "message": f"Downloaded {os.path.basename(src)} from {dest_host} to {dest}"
#         }), 200

#     except Exception as e:
#         print(f"[ERROR] {e}")
#         return jsonify({"error": str(e)}), 500



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
        dest_host = env.get("dest_host") or env.get("dest")
        if not dest_host:
            return jsonify({"error": "dest_host not configured in environment"}), 500
        
        port_str = env.get("port")
        if not port_str:
            return jsonify({"error": "port not configured in environment"}), 500
        
        try:
            port = int(port_str)
        except ValueError:
            return jsonify({"error": f"Invalid port value: {port_str}"}), 500
        
        certi = env.get("certi")  # This can be None

        print(f"[API] Transfer: {src} -> {dest_host}:{port} -> {dest}")
        print(f"[API] File size: {len(filedata)} bytes")
        
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