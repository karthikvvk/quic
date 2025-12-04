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
    Send a command to remote QUIC server with improved reliability
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
                "dest": dest,
                "size": len(filedata)  # Add size for verification
            }).encode()
            
            print(f"[QUIC] Sending command: {command}, src: {src}, dest: {dest}")
            
            # Send header + delimiter
            client._quic.send_stream_data(stream_id, header + b"\n", end_stream=False)
            client.transmit()
            
            # Wait for header to be acknowledged
            await asyncio.sleep(0.1)
            
            # Send file data if present
            if filedata:
                print(f"[QUIC] Sending {len(filedata)} bytes")
                offset = 0
                total_size = len(filedata)
                
                while offset < total_size:
                    chunk = filedata[offset:offset + CHUNK_SIZE]
                    is_last = (offset + len(chunk)) >= total_size
                    
                    client._quic.send_stream_data(stream_id, chunk, end_stream=is_last)
                    client.transmit()
                    
                    offset += len(chunk)
                    
                    # Progress feedback
                    if offset % (CHUNK_SIZE * 10) == 0 or is_last:
                        progress = (offset / total_size) * 100
                        print(f"[QUIC] Progress: {progress:.1f}% ({offset}/{total_size} bytes)")
                    
                    # Adaptive delay based on chunk size
                    await asyncio.sleep(0.02)
                
                # Wait longer for large files
                wait_time = min(2.0, 0.5 + (total_size / (1024 * 1024)))  # Scale with file size
                print(f"[QUIC] Waiting {wait_time:.2f}s for transmission to complete...")
                await asyncio.sleep(wait_time)
                
            else:
                # No file data, close stream
                client._quic.send_stream_data(stream_id, b"", end_stream=True)
                client.transmit()
                await asyncio.sleep(0.5)
            
            # Try to receive acknowledgment (if server implements it)
            try:
                # Wait a bit for potential response
                await asyncio.sleep(0.2)
                
                # Check for any received data on the stream
                events = client._quic._events
                for event in events:
                    if hasattr(event, 'stream_id') and event.stream_id == stream_id:
                        if hasattr(event, 'data'):
                            response = event.data.decode('utf-8', errors='ignore')
                            print(f"[QUIC] Server response: {response}")
            except Exception as e:
                # Acknowledgment is optional, don't fail if not present
                print(f"[QUIC] No acknowledgment received (this is OK): {e}")
            
            print(f"[QUIC] Command sent successfully")
            
    except ConnectionRefusedError:
        print(f"[QUIC] Connection refused by {host}:{port}")
        raise Exception(f"Cannot connect to {host}:{port} - is the QUIC server running?")
    except asyncio.TimeoutError:
        print(f"[QUIC] Timeout connecting to {host}:{port}")
        raise Exception(f"Timeout connecting to {host}:{port}")
    except Exception as e:
        print(f"[QUIC] Error: {e}")
        import traceback
        traceback.print_exc()
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
    Transfer file to remote peer via QUIC with retry logic
    """
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        src = data.get('src')
        dest = data.get('dest')

        if not src:
            return jsonify({"error": "src (source file path) is required"}), 400
        if not dest:
            return jsonify({"error": "dest (destination file path) is required"}), 400

        # Validate source file exists
        if not os.path.exists(src):
            return jsonify({"error": f"Source file not found: {src}"}), 404
        
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
        
        # Get destination host - try multiple keys
        dest_host = data.get("dest_host")  # Allow override from request
        if not dest_host:
            dest_host = env.get("dest_host") or env.get("DEST_HOST") or env.get("dest")
        
        if not dest_host:
            return jsonify({
                "error": "dest_host not configured. Set DEST_HOST in .env or provide dest_host in request body",
                "env_keys": list(env.keys())
            }), 500
        
        # Get port
        port_str = data.get("port")  # Allow override from request
        if not port_str:
            port_str = env.get("port") or env.get("PORT")
        
        if not port_str:
            return jsonify({
                "error": "port not configured. Set PORT in .env or provide port in request body",
                "env_keys": list(env.keys())
            }), 500
        
        try:
            port = int(port_str)
        except ValueError:
            return jsonify({"error": f"Invalid port value: {port_str}"}), 500
        
        # Get certificate (optional)
        certi = env.get("certi") or env.get("CERTI")

        print(f"[API] Transfer: {src} -> {dest_host}:{port} -> {dest}")
        print(f"[API] File size: {len(filedata)} bytes")
        print(f"[API] Certificate: {certi}")
        
        # Retry logic
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[API] Transfer attempt {attempt}/{MAX_RETRIES}")
                
                # Run async QUIC command
                asyncio.run(send_quic_command(
                    host=dest_host,
                    port=port,
                    cert_verify=certi,
                    command="copy",
                    src=os.path.basename(src),
                    dest=dest,
                    filedata=filedata
                ))
                
                # If we get here, transfer succeeded
                print(f"[API] Transfer successful on attempt {attempt}")
                return jsonify({
                    "status": "success",
                    "message": f"Transferred {os.path.basename(src)} to {dest_host}:{dest}",
                    "bytes_transferred": len(filedata),
                    "attempts": attempt
                }), 200
                
            except ConnectionRefusedError as e:
                last_error = e
                error_msg = f"Connection refused to {dest_host}:{port}. Is the QUIC server running?"
                print(f"[API] Attempt {attempt} failed: {error_msg}")
                
            except asyncio.TimeoutError as e:
                last_error = e
                error_msg = f"Timeout connecting to {dest_host}:{port}"
                print(f"[API] Attempt {attempt} failed: {error_msg}")
                
            except Exception as e:
                last_error = e
                error_msg = str(e)
                print(f"[API] Attempt {attempt} failed: {error_msg}")
                import traceback
                traceback.print_exc()
            
            # Retry delay if not last attempt
            if attempt < MAX_RETRIES:
                print(f"[API] Retrying in {RETRY_DELAY}s...")
                import time
                time.sleep(RETRY_DELAY)
            else:
                print(f"[API] All {MAX_RETRIES} attempts failed")
        
        # If we get here, all retries failed
        return jsonify({
            "error": f"QUIC transfer failed after {MAX_RETRIES} attempts",
            "last_error": str(last_error),
            "dest_host": dest_host,
            "port": port
        }), 500

    except Exception as e:
        print(f"[ERROR] Unexpected error in /transfer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": f"Internal server error: {str(e)}",
            "type": type(e).__name__
        }), 500



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