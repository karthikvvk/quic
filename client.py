import argparse
import asyncio
import os
import json
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration
from dotenv import load_dotenv

CHUNK_SIZE = 64 * 1024  # 64KB
ENV_FILE = ".env"



def write_env_file(host, port, certi):
    with open(ENV_FILE, "w") as f:
        f.write(f"HOST={host}\n")
        f.write(f"PORT={port}\n")
        f.write(f"CERTI={certi}\n")

# -------------------------------
# Function to read environment variables from .env file
# -------------------------------
def read_env_file():
    load_dotenv(ENV_FILE)
    host = os.getenv("HOST")
    port = int(os.getenv("PORT", "4433"))  # default 4433 if not set
    certi = os.getenv("CERTI")
    return host, port, certi



async def send_command(host, port, cert_verify, command, src, dest=None):
    config = QuicConfiguration(is_client=True, verify_mode=0)
    if cert_verify:
        config.load_verify_locations(cert_verify)

    async with connect(host, port, configuration=config) as client:
        stream_id = client._quic.get_next_available_stream_id(is_unidirectional=False)
        print(f"[+] sending command on stream {stream_id}")

        # Send JSON header first
        header = json.dumps({
            "command": command,
            "src": os.path.basename(src),
            "dest": dest
        }).encode()
        client._quic.send_stream_data(stream_id, header + b"\n", end_stream=False)
        client.transmit()

        # Handle commands
        if command in ["copy", "move"]:
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
            # For these, just close the stream after sending header
            client._quic.send_stream_data(stream_id, b"", end_stream=True)
            client.transmit()

        await asyncio.sleep(0.5)
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", choices=["copy", "move", "create", "delete"], required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--dest", default=None)
    args = parser.parse_args()



    # else:
        # Read values from .env file
    host, port, certi = read_env_file()
    asyncio.run(send_command(host, port, certi, command="move", src="./test.txt", dest="remote.txt"))
    # asyncio.run(send_command(host, port, certi, args.command, args.src, args.dest))
