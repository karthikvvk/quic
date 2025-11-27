import argparse
import asyncio
import os
import json
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import StreamDataReceived
from aioquic.quic.configuration import QuicConfiguration

class FileReceiverProtocol(QuicConnectionProtocol):
    def __init__(self, *args, out_dir="received_files", **kwargs):
        super().__init__(*args, **kwargs)
        self.out_dir = out_dir
        self._streams = {}  # stream_id -> bytearray

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            data = event.data

            if stream_id not in self._streams:
                self._streams[stream_id] = bytearray()
            self._streams[stream_id].extend(data)

            if event.end_stream:
                payload = self._streams.pop(stream_id).decode(errors="ignore")
                header, _, filedata = payload.partition("\n")

                try:
                    cmd = json.loads(header)
                except Exception as e:
                    print(f"[!] Invalid header: {e}")
                    return

                src = cmd.get("src")
                dest = cmd.get("dest")
                command = cmd.get("command")

                os.makedirs(self.out_dir, exist_ok=True)

                if command == "copy":
                    filename = os.path.join(self.out_dir, dest or src)
                    with open(filename, "wb") as f:
                        f.write(filedata.encode() if isinstance(filedata, str) else filedata)
                    print(f"[+] Copied file to {filename}")

                elif command == "move":
                    if src and dest:
                        os.rename(os.path.join(self.out_dir, src), os.path.join(self.out_dir, dest))
                        print(f"[+] Moved {src} -> {dest}")

                elif command == "create":
                    if dest:
                        open(os.path.join(self.out_dir, dest), "w").close()
                        print(f"[+] Created empty file {dest}")

                elif command == "delete":
                    if src:
                        os.remove(os.path.join(self.out_dir, src))
                        print(f"[+] Deleted {src}")

async def main(host, port, cert, key, out_dir):
    print(f"Starting QUIC server on {host}:{port}")
    configuration = QuicConfiguration(is_client=False)
    configuration.load_cert_chain(cert, key)

    await serve(
        host,
        port,
        configuration=configuration,
        create_protocol=lambda *a, **k: FileReceiverProtocol(*a, out_dir=out_dir, **k),
    )
    await asyncio.Future()

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
        print("Server stopped")