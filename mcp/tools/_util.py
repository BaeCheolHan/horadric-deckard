import json
import os
import urllib.parse
from enum import Enum
from typing import Any, Dict, Optional, List, Callable

# --- Constants & Enums ---

class ErrorCode(str, Enum):
    INVALID_ARGS = "INVALID_ARGS"
    NOT_INDEXED = "NOT_INDEXED"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    IO_ERROR = "IO_ERROR"
    DB_ERROR = "DB_ERROR"
    INTERNAL = "INTERNAL"

# --- Format Selection ---

def _get_format() -> str:
    """
    Returns 'pack' or 'json'.
    Default is 'pack'.
    'json' is used if DECKARD_FORMAT=json.
    """
    fmt = os.environ.get("DECKARD_FORMAT", "pack").strip().lower()
    return "json" if fmt == "json" else "pack"

def _compact_enabled() -> bool:
    """Legacy compact check for JSON mode."""
    val = (os.environ.get("DECKARD_RESPONSE_COMPACT") or "1").strip().lower()
    return val not in {"0", "false", "no", "off"}

# --- PACK1 Encoders ---

def pack_encode_text(s: Any) -> str:
    """
    ENC_TEXT: safe=""
    Used for snippet, msg, reason, detail, hint.
    """
    return urllib.parse.quote(str(s), safe="")

def pack_encode_id(s: Any) -> str:
    """
    ENC_ID: safe="/._-:@"
    Used for path, repo, name (identifiers).
    """
    return urllib.parse.quote(str(s), safe="/._-:@")

# --- PACK1 Builders ---

def pack_header(tool: str, kv: Dict[str, Any], returned: Optional[int] = None, 
                total: Optional[int] = None, total_mode: Optional[str] = None) -> str:
    """
    Builds the PACK1 header line.
    PACK1 <tool> k=v ... [returned=<N>] [total=<M>] [total_mode=<mode>]
    """
    parts = ["PACK1", tool]
    
    # Add custom KV pairs
    for k, v in kv.items():
        parts.append(f"{k}={v}")

    if returned is not None:
        parts.append(f"returned={returned}")
    
    if total_mode:
        parts.append(f"total_mode={total_mode}")
        
    if total is not None and total_mode != "none":
        parts.append(f"total={total}")
        
    return " ".join(parts)

def pack_line(kind: str, kv: Optional[Dict[str, str]] = None, single_value: Optional[str] = None) -> str:
    """
    Builds a PACK1 record line.
    If single_value is provided: <kind>:<single_value>
    If kv is provided: <kind>:k=v k2=v2 ...
    """
    if single_value is not None:
        return f"{kind}:{single_value}"
        
    if kv:
        field_strs = [f"{k}={v}" for k, v in kv.items()]
        return f"{kind}:{ ' '.join(field_strs) }"
        
    return f"{kind}:"

def pack_error(tool: str, code: ErrorCode, msg: str, hints: List[str] = None, trace: str = None) -> str:
    """
    Generates PACK1 error response.
    PACK1 <tool> ok=false
    e:code=<CODE> msg=<ENCODED_MSG>
    d:hint=...
    """
    lines = [f"PACK1 {tool} ok=false"]
    lines.append(f"e:code={code.value} msg={pack_encode_text(msg)}")
    
    if hints:
        for h in hints:
            lines.append(f"d:hint={pack_encode_text(h)}")
            
    if trace:
        lines.append(f"d:trace={pack_encode_text(trace)}")
        
    return "\n".join(lines)

def pack_truncated(next_offset: int, limit: int, truncated_state: str) -> str:
    """
    m:truncated=true|maybe next=use_offset offset=<nextOffset> limit=<limit>
    """
    return f"m:truncated={truncated_state} next=use_offset offset={next_offset} limit={limit}"

# --- Main Utility ---

def mcp_response(
    tool_name: str, 
    pack_func: Callable[[], str], 
    json_func: Callable[[], Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Helper to dispatch between PACK1 and JSON based on configuration.
    
    pack_func: function that returns (str) - the full PACK1 text payload.
    json_func: function that returns (dict) - the dict for JSON serialization.
    """
    fmt = _get_format()
    
    try:
        if fmt == "pack":
            text_output = pack_func()
            return {
                "content": [{"type": "text", "text": text_output}]
            }
        else:
            # JSON mode (Legacy/Debug)
            data = json_func()
            
            if _compact_enabled():
                json_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            else:
                json_text = json.dumps(data, ensure_ascii=False, indent=2)
                
            res = {"content": [{"type": "text", "text": json_text}]}
            if isinstance(data, dict):
                res.update(data)
            return res
    except Exception as e:
        import traceback
        err_msg = str(e)
        stack = traceback.format_exc()
        
        if fmt == "pack":
            return {
                "content": [{"type": "text", "text": pack_error(tool_name, ErrorCode.INTERNAL, err_msg, trace=stack)}],
                "isError": True
            }
        else:
            err_obj = {
                "error": {"code": ErrorCode.INTERNAL.value, "message": err_msg, "trace": stack},
                "isError": True
            }
            return mcp_json(err_obj)


def mcp_json(obj):
    """Utility to format dictionary as standard MCP response."""
    if _compact_enabled():
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        payload = json.dumps(obj, ensure_ascii=False, indent=2)
    res = {"content": [{"type": "text", "text": payload}]}
    if isinstance(obj, dict):
        res.update(obj)
    return res
