import ast
import json
import difflib
import os
import shutil
import subprocess
from typing import Any, Dict, List

try:
    from ._util import (
        mcp_response,
        pack_header,
        pack_line,
        pack_encode_text,
        pack_encode_id,
        pack_error,
        ErrorCode,
        resolve_db_path,
        resolve_fs_path,
    )
except ImportError:
    from _util import (
        mcp_response,
        pack_header,
        pack_line,
        pack_encode_text,
        pack_encode_id,
        pack_error,
        ErrorCode,
        resolve_db_path,
        resolve_fs_path,
    )


def _read_current(db: Any, db_path: str, roots: List[str]) -> str:
    fs_path = resolve_fs_path(db_path, roots)
    if fs_path:
        try:
            with open(fs_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            pass
    raw = db.read_file_raw(db_path) if hasattr(db, "read_file_raw") else db.read_file(db_path)
    return raw or ""


def _syntax_check(path: str, content: str) -> Dict[str, Any]:
    if path.endswith(".py"):
        try:
            ast.parse(content)
            return {"syntax_ok": True}
        except Exception as e:
            return {"syntax_ok": False, "syntax_error": str(e)}
    if path.endswith(".json"):
        try:
            json.loads(content)
            return {"syntax_ok": True}
        except Exception as e:
            return {"syntax_ok": False, "syntax_error": str(e)}
    return {"syntax_ok": True}

def _maybe_lint(path: str, content: str) -> Dict[str, Any]:
    enabled = os.environ.get("SARI_DRYRUN_LINT", "").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return {"lint_skipped": True, "lint_reason": "disabled"}
    ext = path.lower()
    if ext.endswith(".py") and shutil.which("ruff"):
        try:
            proc = subprocess.run(
                ["ruff", "check", "--quiet", "--stdin-filename", path, "-"],
                input=content.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            output = (proc.stdout or b"").decode("utf-8", errors="ignore").strip()
            err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
            return {
                "lint_tool": "ruff",
                "lint_ok": proc.returncode == 0,
                "lint_output": output,
                "lint_error": err,
            }
        except Exception as e:
            return {"lint_ok": False, "lint_error": str(e), "lint_tool": "ruff"}
    if (ext.endswith(".js") or ext.endswith(".ts") or ext.endswith(".jsx") or ext.endswith(".tsx")) and shutil.which("eslint"):
        try:
            proc = subprocess.run(
                ["eslint", "--stdin", "--stdin-filename", path],
                input=content.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            output = (proc.stdout or b"").decode("utf-8", errors="ignore").strip()
            err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
            return {
                "lint_tool": "eslint",
                "lint_ok": proc.returncode == 0,
                "lint_output": output,
                "lint_error": err,
            }
        except Exception as e:
            return {"lint_ok": False, "lint_error": str(e), "lint_tool": "eslint"}
    return {"lint_skipped": True, "lint_reason": "tool_not_found"}


def build_dry_run_diff(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    path = str(args.get("path") or "").strip()
    new_content = str(args.get("content") or "")
    if not path or new_content is None:
        raise ValueError("path and content are required")
    db_path = resolve_db_path(path, roots)
    if not db_path:
        raise ValueError("path is out of workspace scope")
    current = _read_current(db, db_path, roots)
    diff_lines = list(
        difflib.unified_diff(
            current.splitlines(),
            new_content.splitlines(),
            fromfile=f"{db_path} (current)",
            tofile=f"{db_path} (proposed)",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines)
    syntax = _syntax_check(path, new_content)
    lint = _maybe_lint(path, new_content)
    payload = {"path": db_path, "diff": diff_text}
    payload.update(syntax)
    payload.update(lint)
    return payload


def execute_dry_run_diff(args: Dict[str, Any], db: Any, roots: List[str]) -> Dict[str, Any]:
    try:
        payload = build_dry_run_diff(args, db, roots)
    except ValueError as e:
        return mcp_response(
            "dry_run_diff",
            lambda: pack_error("dry_run_diff", ErrorCode.INVALID_ARGS, str(e)),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": str(e)}, "isError": True},
        )

    def build_pack() -> str:
        lines = [pack_header("dry_run_diff", {"path": pack_encode_id(payload["path"])}, returned=1)]
        lines.append(pack_line("m", {"syntax_ok": str(bool(payload.get("syntax_ok", True))).lower()}))
        if payload.get("syntax_error"):
            lines.append(pack_line("m", {"syntax_error": pack_encode_text(payload["syntax_error"])}))
        if "lint_ok" in payload:
            lines.append(pack_line("m", {"lint_ok": str(bool(payload.get("lint_ok"))).lower(), "lint_tool": pack_encode_text(payload.get("lint_tool", ""))}))
        if payload.get("lint_error"):
            lines.append(pack_line("m", {"lint_error": pack_encode_text(payload["lint_error"])}))
        lines.append(pack_line("d", single_value=pack_encode_text(payload.get("diff", ""))))
        return "\n".join(lines)

    return mcp_response(
        "dry_run_diff",
        build_pack,
        lambda: payload,
    )
