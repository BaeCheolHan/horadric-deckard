import json
import os


def _compact_enabled() -> bool:
    val = (os.environ.get("DECKARD_RESPONSE_COMPACT") or "1").strip().lower()
    return val not in {"0", "false", "no", "off"}


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
