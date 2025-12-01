import asyncio
import os
import json
from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import StreamDataReceived
from aioquic.quic.configuration import QuicConfiguration
from startsetup import load_env_vars


def _safe_path(path: str) -> str:
    """
    Normalize and validate path.
    Prevents basic path traversal attacks while allowing absolute paths.
    """
    normalized = os.path.normpath(path)
    # Prevent going outside filesystem root or using relative exploits
    if ".." in normalized.split(os.sep):
        raise ValueError(f"Path traversal detected: {path}")
    return normalized


class FileReceiverProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
                header_bytes, sep, filedata = payload.partition(b"\n")

                try:
                    cmd = json.loads(header_bytes.decode("utf-8", errors="ignore"))
                except Exception as e:
                    print(f"[!] Invalid header: {e}")
                    return

                src = cmd.get("src", "")  # Full path or filename
                dest = cmd.get("dest", "")  # Destination directory (absolute)
                command = cmd.get("command")

                print(f"[DEBUG] Command: {command}, src: {src}, dest: {dest}")

                try:
                    if command == "copy":
                        if not dest:
                            print(f"[!] Copy requires 'dest' path")
                            return
                        
                        target_dir = _safe_path(dest)
                        os.makedirs(target_dir, exist_ok=True)
                        
                        filename = os.path.basename(src)
                        target_file = os.path.join(target_dir, filename)
                        
                        with open(target_file, "wb") as f:
                            f.write(filedata)
                        print(f"[+] Copied {filename} to {target_file}")

                    elif command == "move":
                        if not dest:
                            print(f"[!] Move requires 'dest' path")
                            return
                        
                        target_dir = _safe_path(dest)
                        os.makedirs(target_dir, exist_ok=True)
                        
                        filename = os.path.basename(src)
                        target_file = os.path.join(target_dir, filename)
                        
                        with open(target_file, "wb") as f:
                            f.write(filedata)
                        print(f"[+] Moved {filename} to {target_file}")

                    elif command == "create":
                        if not src:
                            print(f"[!] Create requires 'src' path")
                            return
                        
                        target_path = _safe_path(src)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        open(target_path, "w").close()
                        print(f"[+] Created {target_path}")

                    elif command == "delete":
                        if not src:
                            print(f"[!] Delete requires 'src' path")
                            return
                        
                        target_path = _safe_path(src)
                        
                        if os.path.exists(target_path):
                            os.remove(target_path)
                            print(f"[+] Deleted {target_path}")
                        else:
                            print(f"[!] File not found: {target_path}")

                    else:
                        print(f"[!] Unknown command: {command}")

                except ValueError as ve:
                    print(f"[!] Path error: {ve}")
                except Exception as e:
                    print(f"[!] Operation error: {e}")


async def main(host, port, cert, key):
    print(f"Starting QUIC server on {host}:{port}")
    print(f"Certificate: {cert}")
    print(f"Note: All commands require explicit absolute paths")
    
    configuration = QuicConfiguration(is_client=False)
    configuration.load_cert_chain(cert, key)

    await serve(
        host,
        port,
        configuration=configuration,
        create_protocol=FileReceiverProtocol,
    )
    await asyncio.Future()


if __name__ == "__main__":
    try:
        env = load_env_vars()
        
        host = env["host"]
        port = int(env["port"])
        cert = env["certi"]
        key = env["key"]
        # base_dir no longer needed
        
        asyncio.run(main(host, port, cert, key))
    except KeyboardInterrupt:
        print("\nServer stopped")
    except KeyError as e:
        print(f"[!] Missing required environment variable: {e}")
    except Exception as e:
        print(f"[!] Error starting server: {e}")