import json
import logging
import asyncio
import inspect
import os
import urllib.parse
from typing import Dict, Any, Optional
from .workspace_registry import Registry, SharedState

try:
    from sari.version import __version__ as _SARI_VERSION
except Exception:
    _SARI_VERSION = "dev"
_SARI_PROTOCOL_VERSION = "2025-11-25"
_SARI_BOOT_ID = (os.environ.get("SARI_BOOT_ID") or "").strip()
from sari.core.workspace import WorkspaceManager
from sari.core.server_registry import ServerRegistry

logger = logging.getLogger(__name__)

class Session:
    """
    Handles a single client connection.
    Parses JSON-RPC, manages workspace binding via Registry.
    """
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.workspace_root: Optional[str] = None
        self.shared_state: Optional[SharedState] = None
        self.registry = Registry.get_instance()
        self.running = True

    async def handle_connection(self):
        try:
            while self.running:
                # 1. Read first line to detect framing mode
                line = await self.reader.readline()
                if not line:
                    self.running = False
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                if line_str.startswith("{"):
                    # JSONL mode: First line is the JSON body
                    request_str = line_str
                elif line_str.lower().startswith("content-length:"):
                    # Content-Length mode: Parse headers
                    headers = {}
                    parts = line_str.split(":", 1)
                    headers[parts[0].strip().lower()] = parts[1].strip()
                    
                    while True:
                        h_line = await self.reader.readline()
                        if not h_line:
                            break
                        h_str = h_line.decode("utf-8").strip()
                        if not h_str:
                            break
                        if ":" in h_str:
                            k, v = h_str.split(":", 1)
                            headers[k.strip().lower()] = v.strip()
                    
                    try:
                        content_length = int(headers.get("content-length", 0))
                    except (ValueError, TypeError):
                        continue

                    if content_length <= 0:
                        continue

                    body = await self.reader.readexactly(content_length)
                    if not body:
                        break
                    request_str = body.decode("utf-8")
                else:
                    # Unknown line, skip
                    logger.warning(f"Unknown input line in session: {line_str!r}")
                    continue

                try:
                    request = json.loads(request_str)
                    await self.process_request(request)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {request_str[:100]!r}")
                    await self.send_error(None, -32700, "Parse error")
                except Exception as e:
                    logger.error(f"Error processing request: {e}", exc_info=True)
                    await self.send_error(None, -32603, str(e))

        except (asyncio.IncompleteReadError, ConnectionResetError):
            logger.info("Connection closed by client")
        finally:
            self.cleanup()
            try:
                res = self.writer.close()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                pass
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

    async def process_request(self, request: Dict[str, Any]):
        method = request.get("method")
        params = request.get("params", {})
        msg_id = request.get("id")

        if self.workspace_root:
            self.registry.touch_workspace(self.workspace_root)

        if method == "sari/identify":
            draining = False
            if _SARI_BOOT_ID:
                try:
                    info = ServerRegistry().get_daemon(_SARI_BOOT_ID) or {}
                    draining = bool(info.get("draining"))
                except Exception:
                    draining = False
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "name": "sari",
                    "version": _SARI_VERSION,
                    "protocolVersion": _SARI_PROTOCOL_VERSION,
                    "bootId": _SARI_BOOT_ID,
                    "draining": draining,
                },
            }
            await self.send_json(response)
            return
        if method == "initialize":
            await self.handle_initialize(request)
        elif method == "initialized":
            # Just forward to server if bound
            if self.shared_state:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self.shared_state.server.handle_initialized,
                    params
                )
        elif method == "shutdown":
            # Respond to shutdown but keep connection open for exit
            response = {"jsonrpc": "2.0", "id": msg_id, "result": None}
            await self.send_json(response)
        elif method == "exit":
            self.running = False
        else:
            # Forward other requests to the bound server
            if not self.shared_state:
                await self.send_error(msg_id, -32002, "Server not initialized. Send 'initialize' first.")
                return

            # Execute in thread pool to not block async loop
            # Since LocalSearchMCPServer is synchronous
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.shared_state.server.handle_request,
                request
            )

            if response:
                await self.send_json(response)

    async def handle_initialize(self, request: Dict[str, Any]):
        params = request.get("params", {})
        msg_id = request.get("id")

        if _SARI_BOOT_ID:
            try:
                info = ServerRegistry().get_daemon(_SARI_BOOT_ID) or {}
                if info.get("draining"):
                    await self.send_error(msg_id, -32001, "Server is draining. Reconnect to the latest daemon.")
                    self.running = False
                    return
            except Exception:
                pass

        root_uri = params.get("rootUri") or params.get("rootPath")
        if not root_uri:
            # Fallback for clients that omit rootUri/rootPath
            root_uri = WorkspaceManager.resolve_workspace_root()

        if root_uri.startswith("file://"):
            parsed = urllib.parse.urlparse(root_uri)
            if parsed.netloc and parsed.netloc not in {"localhost", "127.0.0.1", "::1"}:
                await self.send_error(msg_id, -32000, "Unsupported file URI host")
                return
            workspace_root = urllib.parse.unquote(parsed.path)
        else:
            workspace_root = root_uri

        # If already bound to a different workspace, release it
        if self.workspace_root and self.workspace_root != workspace_root:
            self.registry.release(self.workspace_root)
            self.shared_state = None

        self.workspace_root = workspace_root
        self.shared_state = self.registry.get_or_create(self.workspace_root)
        self.registry.touch_workspace(self.workspace_root)

        # Record workspace mapping in global registry so other clients can find us
        if _SARI_BOOT_ID:
            try:
                ServerRegistry().set_workspace(workspace_root, _SARI_BOOT_ID)
            except Exception:
                pass

        # Delegate specific initialize logic to the server instance
        # We need to construct the result based on server's response
        # LocalSearchMCPServer.handle_initialize returns the result dict directly
        try:
            result = self.shared_state.server.handle_initialize(params)
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result
            }
            await self.send_json(response)
        except Exception as e:
            # Rollback: release the workspace if initialization failed
            self.registry.release(self.workspace_root)
            self.workspace_root = None
            self.shared_state = None
            await self.send_error(msg_id, -32000, str(e))

    async def send_json(self, data: Dict[str, Any]):
        body = json.dumps(data).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        res = self.writer.write(header + body)
        if inspect.isawaitable(res):
            await res
        await self.writer.drain()

    async def send_error(self, msg_id: Any, code: int, message: str):
        response = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        await self.send_json(response)

    def cleanup(self):
        if self.workspace_root:
            self.registry.release(self.workspace_root)
            self.workspace_root = None
            self.shared_state = None
