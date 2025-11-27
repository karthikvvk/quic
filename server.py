# server.py
import argparse
import asyncio
import os
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import StreamDataReceived

class FileReceiverProtocol(QuicConnectionProtocol):
    def __init__(self, *args, out_dir="received_files", **kwargs):
        super().__init__(*args, **kwargs)
        self.out_dir = out_dir
        self._streams = {}  # stream_id -> bytearray

    def quic_event_received(self, event):
        # called by aioquic for QUIC events
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            data = event.data
            if stream_id not in self._streams:
                # new stream -> create buffer
                self._streams[stream_id] = bytearray()
            self._streams[stream_id].extend(data)

            if event.end_stream:
                # write file for this stream
                os.makedirs(self.out_dir, exist_ok=True)
                filename = os.path.join(self.out_dir, f"stream-{stream_id}.bin")
                with open(filename, "wb") as f:
                    f.write(self._streams.pop(stream_id))
                print(f"[+] wrote {filename} ({os.path.getsize(filename)} bytes)")

async def main(host, port, cert, key, out_dir):
    print(f"Starting QUIC server on {host}:{port}")
    await serve(
        host,
        port,
        configuration={
            "certificate": cert,
            "private_key": key,
            # high-level: pass to QuicConfiguration in modern versions; shown simply here
        },
        create_protocol=lambda *a, **k: FileReceiverProtocol(*a, out_dir=out_dir, **k),
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4433)
    parser.add_argument("--cert", default="cert.pem")
    parser.add_argument("--key", default="key.pem")
    parser.add_argument("--out-dir", default="received_files")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port, args.cert, args.key, args.out_dir))
    except KeyboardInterrupt:
        pass
