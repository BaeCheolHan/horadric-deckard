import json
import logging
import asyncio
from typing import Dict, Any, Optional
from .registry import Registry, SharedState
from .workspace import WorkspaceManager

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
                data = await self.reader.readline()
                if not data:
                    break
                
                message = data.decode('utf-8').strip()
                if not message:
                    continue
                
                try:
                    request = json.loads(message)
                    await self.process_request(request)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {message}")
                    await self.send_error(None, -32700, "Parse error")
                except Exception as e:
                    logger.error(f"Error processing request: {e}", exc_info=True)
                    # Try to get ID if possible
                    msg_id = None
                    try:
                        msg_id = json.loads(message).get("id")
                    except:
                        pass
                    await self.send_error(msg_id, -32603, str(e))

        except ConnectionResetError:
            logger.info("Connection reset by client")
        finally:
            self.cleanup()
            self.writer.close()
            await self.writer.wait_closed()

    async def process_request(self, request: Dict[str, Any]):
        method = request.get("method")
        params = request.get("params", {})
        msg_id = request.get("id")

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
        
        root_uri = params.get("rootUri") or params.get("rootPath")
        if not root_uri:
            # Fallback for clients that omit rootUri/rootPath
            root_uri = WorkspaceManager.detect_workspace()

        # Handle file:// prefix
        if root_uri.startswith("file://"):
            workspace_root = root_uri[7:]
        else:
            workspace_root = root_uri

        # If already bound to a different workspace, release it
        if self.workspace_root and self.workspace_root != workspace_root:
            self.registry.release(self.workspace_root)
            self.shared_state = None

        self.workspace_root = workspace_root
        self.shared_state = self.registry.get_or_create(self.workspace_root)
        
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
        message = json.dumps(data) + "\n"
        self.writer.write(message.encode('utf-8'))
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
