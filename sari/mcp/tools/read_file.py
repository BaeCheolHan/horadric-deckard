from typing import Any, Dict, List
from sari.core.db import LocalSearchDB
from sari.mcp.tools._util import mcp_response, pack_error, ErrorCode, resolve_db_path, pack_header, pack_line, pack_encode_text

def execute_read_file(args: Dict[str, Any], db: LocalSearchDB, roots: List[str]) -> Dict[str, Any]:
    """
    Execute read_file tool.

    Args:
        args: {"path": str}
        db: LocalSearchDB instance
    """
    path = args.get("path")
    if not path:
        return mcp_response(
            "read_file",
            lambda: pack_error("read_file", ErrorCode.INVALID_ARGS, "'path' is required"),
            lambda: {"error": {"code": ErrorCode.INVALID_ARGS.value, "message": "'path' is required"}, "isError": True},
        )

    db_path = resolve_db_path(path, roots)
    if not db_path and db.has_legacy_paths():
        db_path = path
    if not db_path:
        return mcp_response(
            "read_file",
            lambda: pack_error("read_file", ErrorCode.ERR_ROOT_OUT_OF_SCOPE, f"Path out of scope: {path}", hints=["outside final_roots"]),
            lambda: {"error": {"code": ErrorCode.ERR_ROOT_OUT_OF_SCOPE.value, "message": f"Path out of scope: {path}"}, "isError": True},
        )

    content = db.read_file(db_path)
    if content is None:
        return mcp_response(
            "read_file",
            lambda: pack_error(
                "read_file",
                ErrorCode.NOT_INDEXED,
                f"File not found or not indexed: {db_path}",
                hints=["run scan_once", "verify path with search"],
            ),
            lambda: {
                "error": {
                    "code": ErrorCode.NOT_INDEXED.value,
                    "message": f"File not found or not indexed: {db_path}",
                    "hint": "run scan_once | verify path with search",
                },
                "isError": True,
            },
        )

    def build_pack() -> str:
        lines = [pack_header("read_file", {}, returned=1)]
        lines.append(pack_line("t", single_value=pack_encode_text(content)))
        return "\n".join(lines)

    return mcp_response(
        "read_file",
        build_pack,
        lambda: {"content": [{"type": "text", "text": content}]},
    )
