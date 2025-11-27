# client.py
import argparse
import asyncio
import os
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived

CHUNK_SIZE = 64 * 1024  # 64KB

async def send_file(host, port, cert_verify, path):
    # QuicConfiguration:
    config = QuicConfiguration(is_client=True, verify_mode=0)
    if cert_verify:
        # if you want to verify server cert, load CA
        config.load_verify_locations(cert_verify)

    async with connect(host, port, configuration=config) as client:
        # `client` is a QuicConnectionProtocol
        # create a new bidirectional stream id
        stream_id = client._quic.get_next_available_stream_id(is_unidirectional=False)
        print(f"[+] sending on stream {stream_id}")

        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    # finish the stream
                    client._quic.send_stream_data(stream_id, b"", end_stream=True)
                    await client.transmit()  # flush network packets
                    break
                client._quic.send_stream_data(stream_id, chunk, end_stream=False)
                await client.transmit()  # ensure data is pushed to network

        # optionally, wait for graceful close or server ack
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=4433)
    parser.add_argument("--file", required=True)
    parser.add_argument("--cacert", default=None, help="CA cert to verify server (optional)")
    args = parser.parse_args()
    asyncio.run(send_file(args.host, args.port, args.cacert, args.file))
