import json
import os
import importlib
from pathlib import Path
from typing import Any, Dict, List

try:
    from ._util import mcp_response, pack_header, pack_line, pack_encode_text, pack_encode_id
    from .call_graph import PLUGIN_API_VERSION
except Exception:
    from _util import mcp_response, pack_header, pack_line, pack_encode_text, pack_encode_id
    try:
        from call_graph import PLUGIN_API_VERSION  # type: ignore
    except Exception:
        PLUGIN_API_VERSION = 1


def _load_plugins() -> List[str]:
    mod_path = os.environ.get("SARI_CALLGRAPH_PLUGIN", "").strip()
    if not mod_path:
        return []
    return [m.strip() for m in mod_path.split(",") if m.strip()]


def _parse_manifest() -> Dict[str, Any]:
    manifest = os.environ.get("SARI_CALLGRAPH_PLUGIN_MANIFEST", "").strip()
    if not manifest:
        return {"path": "", "valid": True, "plugins": [], "errors": []}
    strict = os.environ.get("SARI_CALLGRAPH_PLUGIN_MANIFEST_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}
    errors: List[str] = []
    try:
        path = Path(manifest).expanduser().resolve()
        if not path.exists():
            errors.append("manifest_missing")
            return {"path": str(path), "valid": False, "plugins": [], "errors": errors}
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {"path": str(path), "valid": True, "plugins": data, "errors": []}
        if isinstance(data, dict):
            items = data.get("plugins") or data.get("modules")
            if isinstance(items, list):
                return {"path": str(path), "valid": True, "plugins": items, "errors": []}
            errors.append("manifest_missing_plugins_list")
        else:
            errors.append("manifest_invalid_type")
    except Exception as e:
        errors.append(f"manifest_error:{e}")
    return {"path": manifest, "valid": False if strict else True, "plugins": [], "errors": errors}


def build_call_graph_health() -> Dict[str, Any]:
    mods = _load_plugins()
    manifest_info = _parse_manifest()
    results = []
    for m in mods:
        try:
            mod = importlib.import_module(m)
            api = getattr(mod, "__callgraph_plugin_api__", None)
            ver = getattr(mod, "__version__", "")
            ok = (api is None) or (int(api) == int(PLUGIN_API_VERSION))
            level = "ok" if ok else "warn"
            expected = PLUGIN_API_VERSION
            msg = "" if ok else f"api_mismatch expected={expected} got={api}"
            results.append({"module": m, "ok": ok, "level": level, "api": api, "version": ver, "expected_api": expected, "message": msg})
        except Exception as e:
            results.append({"module": m, "ok": False, "level": "error", "error": str(e)})
    return {
        "plugin_api": PLUGIN_API_VERSION,
        "plugins": results,
        "manifest": manifest_info,
        "precision_hint": "high (AST) for .py, low (regex) for JS/TS/Java/Kotlin/Go/C/C++",
        "quality_score": "0-100 (higher means more reliable static resolution)",
    }


def execute_call_graph_health(args: Dict[str, Any]) -> Dict[str, Any]:
    payload = build_call_graph_health()

    def build_pack() -> str:
        lines = [pack_header("call_graph_health", {}, returned=len(payload.get("plugins", [])))]
        for p in payload.get("plugins", []):
            kv = {
                "module": pack_encode_id(p.get("module", "")),
                "ok": str(bool(p.get("ok", False))).lower(),
                "api": str(p.get("api", "")),
                "version": pack_encode_text(p.get("version", "")),
                "level": pack_encode_id(p.get("level", "")),
                "expected_api": str(p.get("expected_api", "")),
            }
            if p.get("error"):
                kv["error"] = pack_encode_text(p.get("error", ""))
            if p.get("message"):
                kv["message"] = pack_encode_text(p.get("message", ""))
            lines.append(pack_line("r", kv))
        lines.append(pack_line("m", {"plugin_api": str(payload.get("plugin_api", 1))}))
        if payload.get("manifest"):
            m = payload.get("manifest", {})
            lines.append(pack_line("m", {"manifest": pack_encode_text(json.dumps(m, ensure_ascii=False))}))
        if payload.get("precision_hint"):
            lines.append(pack_line("m", {"precision_hint": pack_encode_text(payload.get("precision_hint", ""))}))
        if payload.get("quality_score"):
            lines.append(pack_line("m", {"quality_score": pack_encode_text(payload.get("quality_score", ""))}))
        return "\n".join(lines)

    return mcp_response(
        "call_graph_health",
        build_pack,
        lambda: payload,
    )
