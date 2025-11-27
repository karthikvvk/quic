import argparse
import asyncio
import os
import json
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

CHUNK_SIZE = 64 * 1024  # 64KB

async def send_command(host, port, cert_verify, command, src, dest=None):
    config = QuicConfiguration(is_client=True, verify_mode=0)
    if cert_verify:
        config.load_verify_locations(cert_verify)

    async with connect(host, port, configuration=config) as client:
        stream_id = client._quic.get_next_available_stream_id(is_unidirectional=False)
        print(f"[+] sending command on stream {stream_id}")

        # Send JSON header first
        header = json.dumps({"command": command, "src": os.path.basename(src), "dest": dest}).encode()
        client._quic.send_stream_data(stream_id, header + b"\n", end_stream=False)
        client.transmit()

        # If command is copy, also send file data
        if command == "copy":
            with open(src, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        client._quic.send_stream_data(stream_id, b"", end_stream=True)
                        client.transmit()
                        break
                    client._quic.send_stream_data(stream_id, chunk, end_stream=False)
                    client.transmit()

        await asyncio.sleep(0.5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=4433)
    parser.add_argument("--command", choices=["copy", "move", "create", "delete"], required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--dest", default=None)
    parser.add_argument("--cacert", default=None)
    args = parser.parse_args()

    asyncio.run(send_command(args.host, args.port, args.cacert, args.command, args.src, args.dest))