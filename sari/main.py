import argparse
import json
import os
import sys

# CRITICAL: Hijack stdout to stderr at the absolute entry point to prevent 
# ANY third-party library noise from breaking the MCP stdio protocol.
_original_stdout = sys.stdout
sys.stdout = sys.stderr

import subprocess
from pathlib import Path
from typing import List

from sari.core.workspace import WorkspaceManager
from sari.core.config import Config
from sari.core.db import LocalSearchDB
from sari.core.engine_registry import get_default_engine


def _write_toml_block(cfg_path: Path, command: str, args: List[str], env: dict) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = cfg_path.read_text(encoding="utf-8").splitlines() if cfg_path.exists() else []
    new_lines = []
    in_sari = False
    for line in lines:
        if line.strip() == "[mcp_servers.sari]":
            in_sari = True
            continue
        if in_sari and line.startswith("[") and line.strip() != "[mcp_servers.sari]":
            in_sari = False
            new_lines.append(line)
            continue
        if not in_sari:
            new_lines.append(line)
    env_kv = ", ".join([f'{k} = "{v}"' for k, v in env.items()])
    block = [
        "[mcp_servers.sari]",
        f'command = "{command}"',
        f"args = {json.dumps(args)}",
        f"env = {{ {env_kv} }}",
        "startup_timeout_sec = 60",
    ]
    new_lines = block + new_lines
    cfg_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _write_json_settings(cfg_path: Path, command: str, args: List[str], env: dict) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    mcp_servers = data.get("mcpServers") or {}
    mcp_servers["sari"] = {"command": command, "args": args, "env": env}
    data["mcpServers"] = mcp_servers
    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cmd_install(host: str, do_print: bool) -> int:
    ssot = WorkspaceManager.resolve_config_path(str(Path.cwd()))
    env = {
        "SARI_CONFIG": ssot,
    }
    args = ["--transport", "stdio", "--format", "pack"]
    command = "sari"

    if do_print:
        payload = {
            "command": command,
            "args": args,
            "env": env,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if host in {"codex", "gemini"}:
        cfg_path = Path.cwd() / f".{host}" / "config.toml"
        _write_toml_block(cfg_path, command, args, env)
        print(f"[sari] Updated {cfg_path}")
        return 0
    if host in {"claude"}:
        if os.name == "nt":
            cfg_path = Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))) / "Claude" / "claude_desktop_config.json"
        else:
            cfg_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        _write_json_settings(cfg_path, command, args, env)
        print(f"[sari] Updated {cfg_path}")
        return 0
    if host in {"cursor"}:
        cfg_path = Path.home() / ".cursor" / "mcp.json"
        _write_json_settings(cfg_path, command, args, env)
        print(f"[sari] Updated {cfg_path}")
        return 0

    print(f"[sari] Unsupported host: {host}", file=sys.stderr)
    return 2


def _cmd_config_show() -> int:
    cfg_path = WorkspaceManager.resolve_config_path(str(Path.cwd()))
    if not Path(cfg_path).exists():
        print("{}")
        return 0
    print(Path(cfg_path).read_text(encoding="utf-8"))
    return 0


def _cmd_roots_list() -> int:
    cfg_path = WorkspaceManager.resolve_config_path(str(Path.cwd()))
    if not Path(cfg_path).exists():
        print("[]")
        return 0
    data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    roots = data.get("roots") or data.get("workspace_roots") or []
    print(json.dumps(roots, ensure_ascii=False, indent=2))
    return 0


def _cmd_roots_add(path: str) -> int:
    cfg_path = WorkspaceManager.resolve_config_path(str(Path.cwd()))
    data = {}
    if Path(cfg_path).exists():
        try:
            data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        except Exception:
            data = {}
    roots = data.get("roots") or data.get("workspace_roots") or []
    roots = [r for r in roots if r]
    roots.append(path)
    final = WorkspaceManager.resolve_workspace_roots(root_uri=None, roots_env={}, config_roots=roots)
    data["roots"] = final
    Path(cfg_path).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg_path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


def _cmd_roots_remove(path: str) -> int:
    cfg_path = WorkspaceManager.resolve_config_path(str(Path.cwd()))
    if not Path(cfg_path).exists():
        print("[]")
        return 0
    data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    roots = data.get("roots") or data.get("workspace_roots") or []
    roots = [r for r in roots if r and r != path]
    data["roots"] = roots
    Path(cfg_path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(roots, ensure_ascii=False, indent=2))
    return 0


def _cmd_index() -> int:
    try:
        from sari.mcp.cli import _request_http
        _request_http("/rescan", {})
        print(json.dumps({"requested": True}))
        return 0
    except Exception as e:
        print(json.dumps({"requested": False, "error": str(e)}))
        return 1


def _cmd_status() -> int:
    try:
        from sari.mcp.cli import _request_http
        data = _request_http("/status", {})
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


def _load_engine_context():
    workspace_root = WorkspaceManager.resolve_workspace_root()
    cfg_path = WorkspaceManager.resolve_config_path(str(Path.cwd()))
    cfg = Config.load(cfg_path, workspace_root_override=workspace_root)
    db = LocalSearchDB(cfg.db_path)
    db.set_engine(get_default_engine(db, cfg, cfg.workspace_roots))
    return cfg, db


def _cmd_engine_status() -> int:
    try:
        _cfg, db = _load_engine_context()
        if hasattr(db.engine, "status"):
            st = db.engine.status()
            print(json.dumps(st.__dict__, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps({"error": "engine status unsupported"}, ensure_ascii=False, indent=2))
        return 1
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


def _cmd_engine_install() -> int:
    try:
        _cfg, db = _load_engine_context()
        if hasattr(db.engine, "install"):
            db.engine.install()
            print(json.dumps({"ok": True}))
            return 0
        print(json.dumps({"error": "engine install unsupported"}))
        return 1
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


def _cmd_engine_rebuild() -> int:
    try:
        _cfg, db = _load_engine_context()
        if hasattr(db.engine, "rebuild"):
            db.engine.rebuild()
            print(json.dumps({"ok": True}))
            return 0
        print(json.dumps({"error": "engine rebuild unsupported"}))
        return 1
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


def _cmd_engine_verify() -> int:
    try:
        _cfg, db = _load_engine_context()
        if hasattr(db.engine, "status"):
            st = db.engine.status()
            if st.engine_ready:
                print(json.dumps({"ok": True}))
                return 0
            print(json.dumps({"ok": False, "reason": st.reason, "hint": st.hint}))
            return 2
        print(json.dumps({"error": "engine status unsupported"}))
        return 1
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


def _cmd_doctor() -> int:
    try:
        from sari.mcp.tools.doctor import execute_doctor
        from urllib.parse import unquote
        
        # Use default args for CLI call
        res = execute_doctor({})
        
        # Parse the 'pack' or 'json' response from execute_doctor
        if isinstance(res, dict) and "content" in res:
            content = res["content"][0]["text"]
            
            # Case 1: JSON response
            try:
                data = json.loads(content)
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return 0
            except Exception:
                pass
            
            # Case 2: PACK1 response (Extract encoded text from t: line)
            if content.startswith("PACK1"):
                lines = content.splitlines()
                for line in lines:
                    if line.startswith("t:"):
                        encoded_val = line[2:]
                        decoded_val = unquote(encoded_val)
                        try:
                            data = json.loads(decoded_val)
                            print(json.dumps(data, ensure_ascii=False, indent=2))
                            return 0
                        except Exception:
                            print(decoded_val)
                            return 0
            
            # Case 3: Raw text fallback
            print(content)
        return 0
    except Exception as e:
        print(f"Doctor failed: {e}", file=sys.stderr)
        return 1


def _should_http_daemon(ns: argparse.Namespace) -> bool:
    if ns.http_daemon:
        return True
    env = (os.environ.get("SARI_HTTP_DAEMON") or "").strip().lower()
    return env in {"1", "true", "yes", "on"}


def _run_http_server() -> int:
    from sari.core.main import main as http_main
    return http_main()


def _set_http_api_port(port: str) -> None:
    if port:
        os.environ["SARI_HTTP_API_PORT"] = str(port)


def _spawn_http_daemon(ns: argparse.Namespace) -> int:
    if os.environ.get("SARI_HTTP_DAEMON_CHILD"):
        return _run_http_server()
    env = os.environ.copy()
    env["SARI_HTTP_DAEMON_CHILD"] = "1"
    cmd = [sys.executable, "-m", "sari", "--transport", "http"]
    if ns.http_api_port:
        cmd += ["--http-api-port", str(ns.http_api_port)]
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    port_note = ns.http_api_port or os.environ.get("SARI_HTTP_API_PORT") or "default"
    print(f"[sari] HTTP daemon started in background (port: {port_note})", file=sys.stderr)
    return 0


def run_cmd(argv: List[str]) -> int:
    if not argv:
        print("missing subcommand", file=sys.stderr)
        return 2
    if argv[0] == "doctor":
        return _cmd_doctor()
    if argv[0] == "status":
        return _cmd_status()
    if argv[0] == "config" and len(argv) > 1 and argv[1] == "show":
        return _cmd_config_show()
    if argv[0] == "roots":
        if len(argv) < 2:
            print("roots add|remove|list", file=sys.stderr)
            return 2
        if argv[1] == "list":
            return _cmd_roots_list()
        if argv[1] == "add" and len(argv) > 2:
            return _cmd_roots_add(argv[2])
        if argv[1] == "remove" and len(argv) > 2:
            return _cmd_roots_remove(argv[2])
    if argv[0] == "index":
        return _cmd_index()
    if argv[0] == "install":
        parser = argparse.ArgumentParser(prog="sari --cmd install")
        parser.add_argument("--host", required=True, choices=["codex", "gemini", "claude", "cursor"])
        parser.add_argument("--print", action="store_true")
        ns = parser.parse_args(argv[1:])
        return _cmd_install(ns.host, ns.print)
    if argv[0] == "engine":
        if len(argv) < 2:
            print("engine status|install|rebuild|verify", file=sys.stderr)
            return 2
        action = argv[1]
        if action == "status":
            return _cmd_engine_status()
        if action == "install":
            return _cmd_engine_install()
        if action == "rebuild":
            return _cmd_engine_rebuild()
        if action == "verify":
            return _cmd_engine_verify()
    if argv[0] == "uninstall":
        from sari import uninstall as uninstall_mod
        return uninstall_mod.main(argv[1:])
    print(f"Unknown subcommand: {argv[0]}", file=sys.stderr)
    return 2


def main(argv: List[str] = None) -> int:
    argv = list(argv or sys.argv[1:])
    # Default to stdio server if no arguments provided, or if explicitly requested
    if not argv:
        # Instead of run_cmd(["status"]), we fall through to the stdio server start
        pass
    else:
        # Fast-path for subcommands
        if argv[0] == "doctor":
            return _cmd_doctor()
        
        if argv[0] in {"daemon", "proxy", "status", "search", "init", "auto"}:
            from sari.mcp.cli import main as legacy_main
            sys.argv = ["sari"] + argv
            return legacy_main()
        if "--cmd" in argv:
            idx = argv.index("--cmd")
            cmd_args = argv[idx + 1 :]
            return run_cmd(cmd_args)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--transport", default="stdio", choices=["stdio", "http"])
    parser.add_argument("--format", default="pack", choices=["pack", "json"])
    parser.add_argument("--http-api", action="store_true")
    parser.add_argument("--http-api-port")
    parser.add_argument("--http-daemon", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--help", action="store_true")
    ns, _ = parser.parse_known_args(argv)

    if ns.help:
        print("sari [--transport stdio|http] [--format pack|json] [--http-api] [--http-api-port PORT] [--http-daemon] [--cmd <subcommand>]")
        return 0
    if ns.version:
        from sari.mcp.server import LocalSearchMCPServer
        print(LocalSearchMCPServer.SERVER_VERSION)
        return 0

    os.environ["SARI_FORMAT"] = ns.format

    if ns.http_api:
        _set_http_api_port(ns.http_api_port)
        if _should_http_daemon(ns):
            return _spawn_http_daemon(ns)
        return _run_http_server()

    if ns.transport == "http":
        _set_http_api_port(ns.http_api_port)
        if _should_http_daemon(ns):
            return _spawn_http_daemon(ns)
        return _run_http_server()

    from sari.mcp.server import main as mcp_main
    # Pass the clean stdout handle to the MCP server
    mcp_main(_original_stdout)
    return 0
