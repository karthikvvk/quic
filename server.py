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

                    elif command == "fetch":
                        # NEW: Handle fetch command - send file back to requester
                        if not src:
                            print(f"[!] Fetch requires 'src' path")
                            self._send_error_response(stream_id, "src path required")
                            return
                        
                        source_path = _safe_path(src)
                        
                        if not os.path.exists(source_path):
                            print(f"[!] File not found: {source_path}")
                            self._send_error_response(stream_id, f"File not found: {source_path}")
                            return
                        
                        if not os.path.isfile(source_path):
                            print(f"[!] Not a file: {source_path}")
                            self._send_error_response(stream_id, f"Not a file: {source_path}")
                            return
                        
                        # Read the file
                        try:
                            with open(source_path, "rb") as f:
                                file_content = f.read()
                            
                            # Send file back
                            response_stream_id = self._quic.get_next_available_stream_id()
                            
                            # Send response header
                            response_header = json.dumps({
                                "status": "success",
                                "src": src,
                                "size": len(file_content)
                            }).encode()
                            
                            self._quic.send_stream_data(response_stream_id, response_header + b"\n", end_stream=False)
                            self.transmit()
                            
                            # Send file data in chunks
                            CHUNK_SIZE = 64 * 1024
                            offset = 0
                            while offset < len(file_content):
                                chunk = file_content[offset:offset + CHUNK_SIZE]
                                is_last = (offset + len(chunk)) >= len(file_content)
                                self._quic.send_stream_data(response_stream_id, chunk, end_stream=is_last)
                                self.transmit()
                                offset += len(chunk)
                            
                            print(f"[+] Sent file {source_path} ({len(file_content)} bytes)")
                            
                        except PermissionError:
                            print(f"[!] Permission denied: {source_path}")
                            self._send_error_response(stream_id, f"Permission denied: {source_path}")
                        except Exception as e:
                            print(f"[!] Error reading file: {e}")
                            self._send_error_response(stream_id, f"Error reading file: {str(e)}")

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
    
    def _send_error_response(self, stream_id, error_msg):
        """Send error response back to client"""
        try:
            response_stream_id = self._quic.get_next_available_stream_id()
            error_header = json.dumps({
                "status": "error",
                "error": error_msg
            }).encode()
            self._quic.send_stream_data(response_stream_id, error_header + b"\n", end_stream=True)
            self.transmit()
        except Exception as e:
            print(f"[!] Failed to send error response: {e}")


async def main(host, port, cert, key):
    print(f"╔═══════════════════════════════════════════════════════╗")
    print(f"║          QUIC File Transfer Server Starting          ║")
    print(f"╚═══════════════════════════════════════════════════════╝")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Certificate: {cert}")
    print(f"  Supported commands: copy, move, create, delete, fetch")
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