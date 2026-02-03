import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

from app.workspace import WorkspaceManager
from app.config import Config
from mcp.tools._util import pack_error, ErrorCode


def _print_transport_error(fmt: str) -> int:
    msg = "MCP-over-HTTP transport is not supported."
    if fmt == "json":
        payload = {"error": {"code": ErrorCode.ERR_MCP_HTTP_UNSUPPORTED.value, "message": msg}}
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(pack_error("server", ErrorCode.ERR_MCP_HTTP_UNSUPPORTED, msg))
    return 1


def _write_toml_block(cfg_path: Path, command: str, args: List[str], env: dict) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = cfg_path.read_text(encoding="utf-8").splitlines() if cfg_path.exists() else []
    new_lines = []
    in_deckard = False
    for line in lines:
        if line.strip() == "[mcp_servers.deckard]":
            in_deckard = True
            continue
        if in_deckard and line.startswith("[") and line.strip() != "[mcp_servers.deckard]":
            in_deckard = False
            new_lines.append(line)
            continue
        if not in_deckard:
            new_lines.append(line)
    env_kv = ", ".join([f'{k} = "{v}"' for k, v in env.items()])
    block = [
        "[mcp_servers.deckard]",
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
    mcp_servers["deckard"] = {"command": command, "args": args, "env": env}
    data["mcpServers"] = mcp_servers
    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cmd_install(host: str, do_print: bool) -> int:
    ssot = WorkspaceManager.resolve_config_path(str(Path.cwd()))
    env = {
        "DECKARD_CONFIG": ssot,
    }
    args = ["--transport", "stdio", "--format", "pack"]
    command = "deckard"

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
        print(f"[deckard] Updated {cfg_path}")
        return 0
    if host in {"claude"}:
        if os.name == "nt":
            cfg_path = Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))) / "Claude" / "claude_desktop_config.json"
        else:
            cfg_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        _write_json_settings(cfg_path, command, args, env)
        print(f"[deckard] Updated {cfg_path}")
        return 0
    if host in {"cursor"}:
        cfg_path = Path.home() / ".cursor" / "mcp.json"
        _write_json_settings(cfg_path, command, args, env)
        print(f"[deckard] Updated {cfg_path}")
        return 0

    print(f"[deckard] Unsupported host: {host}", file=sys.stderr)
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
        from mcp.cli import _request_http
        _request_http("/rescan", {})
        print(json.dumps({"requested": True}))
        return 0
    except Exception as e:
        print(json.dumps({"requested": False, "error": str(e)}))
        return 1


def _cmd_status() -> int:
    try:
        from mcp.cli import _request_http
        data = _request_http("/status", {})
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


def _cmd_doctor() -> int:
    try:
        from doctor import run_doctor
        run_doctor()
        return 0
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1


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
        parser = argparse.ArgumentParser(prog="deckard --cmd install")
        parser.add_argument("--host", required=True, choices=["codex", "gemini", "claude", "cursor"])
        parser.add_argument("--print", action="store_true")
        ns = parser.parse_args(argv[1:])
        return _cmd_install(ns.host, ns.print)
    print(f"Unknown subcommand: {argv[0]}", file=sys.stderr)
    return 2


def main(argv: List[str] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if argv and argv[0] in {"daemon", "proxy", "status", "search", "init", "auto"}:
        from mcp.cli import main as legacy_main
        sys.argv = ["deckard"] + argv
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
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--help", action="store_true")
    ns, _ = parser.parse_known_args(argv)

    if ns.help:
        print("deckard [--transport stdio|http] [--format pack|json] [--http-api] [--cmd <subcommand>]")
        return 0
    if ns.version:
        from mcp.server import LocalSearchMCPServer
        print(LocalSearchMCPServer.SERVER_VERSION)
        return 0

    os.environ["DECKARD_FORMAT"] = ns.format

    if ns.http_api:
        if ns.http_api_port:
            os.environ["DECKARD_HTTP_API_PORT"] = str(ns.http_api_port)
        from app.main import main as http_main
        return http_main()

    if ns.transport == "http":
        return _print_transport_error(ns.format)

    from mcp.server import main as mcp_main
    mcp_main()
    return 0
