import urllib.parse

def parse_pack1(text):
    """
    Parses PACK1 format text into a structured dictionary for testing.
    """
    lines = text.strip().split("\n")
    if not lines:
        return {}

    header = lines[0]
    if not header.startswith("PACK1"):
        raise ValueError(f"Invalid PACK1 header: {header}")

    header_parts = header.split(" ")
    # Extract header KVs
    header_kv = {}
    for part in header_parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            header_kv[k] = urllib.parse.unquote(v)
    tool = header_kv.get("tool", "")

    records = []
    meta = {}
    
    # Error metadata from header (single-line errors)
    if header_kv.get("ok") == "false":
        meta["error"] = {k: v for k, v in header_kv.items() if k not in {"tool", "ok"}}

    for line in lines[1:]:
        if ":" not in line:
            continue
        kind, payload = line.split(":", 1)
        
        if kind == "m" and "truncated=" in payload:
            # Truncation line
            t_kv = {}
            for part in payload.split(" "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    t_kv[k] = urllib.parse.unquote(v)
            meta["truncation"] = t_kv
        elif kind == "e":
            # Legacy error line
            e_kv = {}
            for part in payload.split(" "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    e_kv[k] = urllib.parse.unquote(v)
            meta["error"] = e_kv
        else:
            # Record line
            if "=" in payload:
                # KV record (e.g., h:, r:)
                r_kv = {}
                for part in payload.split(" "):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        r_kv[k] = urllib.parse.unquote(v)
                records.append({"kind": kind, "data": r_kv})
            else:
                # Single value record (e.g., p:)
                records.append({"kind": kind, "value": urllib.parse.unquote(payload)})

    return {
        "tool": tool,
        "header": header_kv,
        "records": records,
        "meta": meta
    }
