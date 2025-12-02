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
                
                # Split header and file data
                try:
                    header_end = payload.index(b"\n")
                    header_bytes = payload[:header_end]
                    filedata = payload[header_end + 1:]
                except ValueError:
                    print(f"[!] No header delimiter found")
                    return

                try:
                    cmd = json.loads(header_bytes.decode("utf-8", errors="ignore"))
                except Exception as e:
                    print(f"[!] Invalid header: {e}")
                    return

                src = cmd.get("src", "")
                dest = cmd.get("dest", "")
                command = cmd.get("command", "copy")

                print(f"[DEBUG] Command: {command}, src: {src}, dest: {dest}")

                try:
                    if command == "copy" or command == "move":
                        if not dest:
                            print(f"[!] {command} requires 'dest' path")
                            return
                        
                        target_path = _safe_path(dest)
                        
                        # Create parent directory if needed
                        parent_dir = os.path.dirname(target_path)
                        if parent_dir:
                            os.makedirs(parent_dir, exist_ok=True)
                        
                        # Write the file
                        with open(target_path, "wb") as f:
                            f.write(filedata)
                        print(f"[+] {command.capitalize()}d to {target_path} ({len(filedata)} bytes)")

                    elif command == "create":
                        if not src:
                            print(f"[!] Create requires 'src' path")
                            return
                        
                        target_path = _safe_path(src)
                        parent_dir = os.path.dirname(target_path)
                        if parent_dir:
                            os.makedirs(parent_dir, exist_ok=True)
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
    print(f"╔═══════════════════════════════════════════════════════╗")
    print(f"║          QUIC File Transfer Server Starting          ║")
    print(f"╚═══════════════════════════════════════════════════════╝")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Certificate: {cert}")
    print(f"  Listening for file operations...")
    print()
    
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
        
        asyncio.run(main(host, port, cert, key))
    except KeyboardInterrupt:
        print("\n\n[!] Server stopped by user")
    except KeyError as e:
        print(f"[!] Missing required environment variable: {e}")
    except Exception as e:
        print(f"[!] Error starting server: {e}")