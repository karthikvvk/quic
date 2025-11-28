from flask import Flask, request, jsonify
import asyncio
import os
import json
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration
from helper import *

app = Flask(__name__)

CHUNK_SIZE = 64 * 1024  # 64KB
ENV_FILE = ".env"


def _normalize_dest(dest: str | None) -> str | None:
    if not dest:
        return None
    # strip trailing slashes and normalize
    return os.path.normpath(dest).strip()


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
            # Always send basename only
            header_dict["src"] = os.path.basename(src)

        if command in ["copy", "move"]:
            header_dict["dest"] = _normalize_dest(dest)

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

        env = read_env_file()
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

        env = read_env_file()
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

        env = read_env_file()
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

        env = read_env_file()
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


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)