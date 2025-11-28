import argparse
import asyncio
import os
import json
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration
from helper import *

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--command",
        choices=["copy", "move", "create", "delete"],
        required=True,
        help="Operation to perform"
    )
    parser.add_argument("--src", help="Filename (basename) required for all commands")
    parser.add_argument("--dest", help="Destination folder (required only for copy/move)")
    args = parser.parse_args()

    # Validation
    if args.command in ["copy", "move"] and (not args.src):
        parser.error("--src and --dest are required for copy/move")
    elif args.command in ["create", "delete"] and not args.src:
        parser.error("--src is required for create/delete")

    env = read_env_file()
    host, port, certi, out_dir, src_env, key = (
        env["host"],
        env["port"],
        env["certi"],
        env["out_dir"],
        env["src"],
        env["key"],
    )

    # src from CLI overrides env
    src = args.src or src_env
    # dest matters only for copy/move; otherwise server uses out_dir implicitly
    dest = args.dest or out_dir

    asyncio.run(send_command(host, port, certi, args.command, src, dest))
