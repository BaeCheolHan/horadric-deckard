import json
import os
import sys
import logging
from typing import Any, Dict, Optional, Tuple, BinaryIO

logger = logging.getLogger("sari.mcp.transport")

_MODE_FRAMED = "content-length"
_MODE_JSONL = "jsonl"
MAX_MESSAGE_SIZE = 10 * 1024 * 1024 # 10MB

class McpTransport:
    """
    Handles the low-level MCP wire protocol (Framing).
    Encapsulates Content-Length and JSONL logic.
    """
    
    def __init__(self, input_stream: BinaryIO, output_stream: BinaryIO, allow_jsonl: bool = False):
        self.input = input_stream
        self.output = output_stream
        self.allow_jsonl = allow_jsonl
        self.default_mode = _MODE_FRAMED

    def read_message(self) -> Optional[Tuple[Dict[str, Any], str]]:
        """
        Reads one MCP message from the input stream.
        Returns: (parsed_dict, framing_mode) or None if EOF/Error.
        """
        try:
            line = self.input.readline()
            if not line:
                return None
            
            while line in (b"\n", b"\r\n"):
                line = self.input.readline()
                if not line:
                    return None

            line_str = line.decode("utf-8", errors="ignore").strip()
            if not line_str:
                return None

            if line_str.startswith("{"):
                # JSONL Mode
                if not self.allow_jsonl and os.environ.get("SARI_DEV_JSONL") != "1":
                    logger.debug("JSONL detected but not allowed. Ignoring.")
                    return None
                return self._parse_json(line_str), _MODE_JSONL

            if line_str.lower().startswith("content-length:"):
                # Content-Length Mode
                content_length = self._parse_headers(line_str)
                if content_length is None or content_length <= 0 or content_length > MAX_MESSAGE_SIZE:
                    return None

                body_bytes = b""
                while len(body_bytes) < content_length:
                    chunk = self.input.read(content_length - len(body_bytes))
                    if not chunk:
                        break
                    body_bytes += chunk
                
                if len(body_bytes) < content_length:
                    return None
                
                return self._parse_json(body_bytes.decode("utf-8")), _MODE_FRAMED

            return None
        except Exception as e:
            logger.error(f"Error reading MCP message: {e}")
            return None

    def write_message(self, message: Dict[str, Any], mode: Optional[str] = None):
        """
        Writes one MCP message to the output stream.
        """
        try:
            json_str = json.dumps(message, ensure_ascii=False)
            mode = mode or self.default_mode
            
            if mode == _MODE_JSONL:
                payload = (json_str + "\n").encode("utf-8")
                self.output.write(payload)
            else:
                body_bytes = json_str.encode("utf-8")
                header = f"Content-Length: {len(body_bytes)}\r\n\r\n".encode("ascii")
                self.output.write(header + body_bytes)
            
            self.output.flush()
        except Exception as e:
            logger.error(f"Error writing MCP message: {e}")

    def _parse_headers(self, first_line: str) -> Optional[int]:
        headers = {}
        parts = first_line.split(":", 1)
        headers[parts[0].strip().lower()] = parts[1].strip()
        
        # Read remaining headers until separator
        while True:
            line = self.input.readline()
            if not line:
                break
            h_str = line.decode("utf-8").strip()
            if not h_str:
                break # Separator
            if ":" in h_str:
                k, v = h_str.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        
        try:
            return int(headers.get("content-length", 0))
        except (ValueError, TypeError):
            return None

    def _parse_json(self, data: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(data)
        except Exception:
            return None

    def close(self) -> None:
        """Best-effort close for non-stdio streams."""
        stdio_streams = {getattr(sys.stdin, "buffer", None), getattr(sys.stdout, "buffer", None), getattr(sys.stderr, "buffer", None)}
        for stream in (self.input, self.output):
            if stream in stdio_streams:
                continue
            try:
                stream.close()
            except Exception:
                pass
