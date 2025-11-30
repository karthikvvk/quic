import asyncio
import os
import json
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import StreamDataReceived
from aioquic.quic.configuration import QuicConfiguration
from startsetup import load_env_vars


def _safe_join(base: str, *paths: str) -> str:
    """
    Join and normalize paths, ensuring the result stays within base.
    Prevents path traversal via src/dest.
    """
    target = os.path.normpath(os.path.join(base, *[p for p in paths if p]))
    base_norm = os.path.normpath(base)
    if not os.path.commonpath([base_norm, target]) == base_norm:
        raise ValueError(f"Unsafe path outside base: {target}")
    return target


class FileReceiverProtocol(QuicConnectionProtocol):
    def __init__(self, *args, out_dir=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.out_dir = out_dir
        self._streams = {}

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            stream_id = event.stream_id
            data = event.data

            if stream_id not in self._streams:
                self._streams[stream_id] = bytearray()
            self._streams[stream_id].extend(data)

            if event.end_stream:
                payload = self._streams.pop(stream_id)
                # Split header and body at first newline byte
                header_bytes, sep, filedata = payload.partition(b"\n")

                try:
                    cmd = json.loads(header_bytes.decode("utf-8", errors="ignore"))
                except Exception as e:
                    print(f"[!] Invalid header: {e}")
                    return

                src = os.path.basename(cmd.get("src") or "")  # filename only
                dest = cmd.get("dest")                        # folder name (for copy/move)
                command = cmd.get("command")

                # Ensure base output directory exists
                os.makedirs(self.out_dir, exist_ok=True)

                try:
                    if command == "copy":
                        folder = _safe_join(self.out_dir, dest or "")
                        os.makedirs(folder, exist_ok=True)
                        filename = _safe_join(folder, src)
                        with open(filename, "wb") as f:
                            f.write(filedata)
                        print(f"[+] Copied file to {filename}")

                    elif command == "move":
                        # Write to dest folder
                        folder = _safe_join(self.out_dir, dest or "")
                        os.makedirs(folder, exist_ok=True)
                        filename = _safe_join(folder, src)
                        with open(filename, "wb") as f:
                            f.write(filedata)

                        # Delete original from out_dir root
                        old_path = src
                        if os.path.exists(old_path):
                            os.remove(old_path)
                            print(f"[+] Deleted original file {old_path}")
                        else:
                            print(f"[!] No original file {old_path} to delete")

                        print(f"[+] Moved {src} -> {filename}")

                    elif command == "create":
                        # Create src under out_dir
                        if not src:
                            print("[!] Missing src for create")
                            return
                        filename = _safe_join(self.out_dir, src)
                        open(filename, "w").close()
                        print(f"[+] Created empty file {filename}")

                    elif command == "delete":
                        # Delete src under out_dir
                        if not src:
                            print("[!] Missing src for delete")
                            return
                        filename = _safe_join(self.out_dir, src)
                        if os.path.exists(filename):
                            os.remove(filename)
                            print(f"[+] Deleted {filename}")
                        else:
                            print(f"[!] File not found: {filename}")

                    else:
                        print(f"[!] Unknown command: {command}")

                except ValueError as ve:
                    print(f"[!] Path error: {ve}")
                except Exception as e:
                    print(f"[!] Operation error: {e}")


async def main(host, port, cert, key, out_dir):
    print(f"Starting QUIC server on {host}:{port}")
    print(f"Certificate: {cert}")
    print(f"Output directory: {out_dir}")
    
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
    try:
        # Load all configuration from environment variables
        env = load_env_vars()
        
        host = env["host"]
        port = int(env["port"])
        cert = env["certi"]
        key = env["key"]
        out_dir = env["out_dir"]
        
        asyncio.run(main(host, port, cert, key, out_dir))
    except KeyboardInterrupt:
        print("\nServer stopped")
    except KeyError as e:
        print(f"[!] Missing required environment variable: {e}")
    except Exception as e:
        print(f"[!] Error starting server: {e}")