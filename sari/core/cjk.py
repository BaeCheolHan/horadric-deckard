import os
import sys
import threading
import zipfile
from pathlib import Path
from typing import Optional, Tuple

from .workspace import WorkspaceManager

_LINDERA_LOCK = threading.Lock()
_LINDERA_TOKENIZER = None
_LINDERA_ERROR = ""
_LINDERA_DICT_PATH = ""
_LINDERA_DICT_URI = ""
_LINDERA_READY = False
_LINDERA_SYS_PATHS: set[str] = set()


def _platform_tokenizer_tag() -> str:
    import platform
    plat = sys.platform
    arch = platform.machine().lower()
    if plat.startswith("darwin"):
        if arch in {"arm64", "aarch64"}:
            return "macosx_11_0_arm64"
        if arch in {"x86_64", "amd64"}:
            return "macosx_10_9_x86_64"
        return "macosx"
    if plat.startswith("win"):
        return "win_amd64"
    if plat.startswith("linux"):
        if arch in {"aarch64", "arm64"}:
            return "manylinux_2_17_aarch64"
        return "manylinux_2_17_x86_64"
    return "unknown"


def _find_tokenizer_bundle() -> Tuple[str, str]:
    try:
        base = Path(__file__).parent / "engine_tokenizer_data"
        tag = _platform_tokenizer_tag()
        if not base.exists():
            return tag, ""
        for p in base.glob("lindera_python_ipadic-*.whl"):
            if tag in p.name:
                return tag, str(p)
        return tag, ""
    except Exception:
        return "unknown", ""


def _ensure_wheel_extracted(bundle_path: str) -> Optional[str]:
    if not bundle_path:
        return None
    try:
        cache_dir = WorkspaceManager.get_engine_cache_dir() / "tokenizer" / _platform_tokenizer_tag() / "lindera_python_ipadic"
        marker = cache_dir / ".extracted"
        if marker.exists():
            return str(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle_path) as zf:
            zf.extractall(cache_dir)
        marker.write_text("ok", encoding="utf-8")
        return str(cache_dir)
    except Exception:
        return None


def _add_sys_path(path: Optional[str]) -> None:
    if not path:
        return
    if path in _LINDERA_SYS_PATHS:
        return
    sys.path.insert(0, path)
    _LINDERA_SYS_PATHS.add(path)


def _find_dict_root(base: Path) -> Optional[str]:
    targets = {"sys.dic", "unk.dic", "matrix.mtx", "char.def", "unk.def"}
    try:
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.name in targets:
                return str(p.parent)
    except Exception:
        return None
    return None


def _resolve_dict_path() -> str:
    env = (os.environ.get("SARI_LINDERA_DICT_PATH") or "").strip()
    if env:
        p = Path(os.path.expanduser(env))
        if p.exists():
            return str(p)
    try:
        import lindera_dictionary_ipadic as ldi  # type: ignore
        mod_path = Path(getattr(ldi, "__file__", ""))
        if mod_path.exists():
            root = _find_dict_root(mod_path.parent)
            if root:
                return root
    except Exception:
        pass
    return ""


def _init_lindera() -> None:
    global _LINDERA_TOKENIZER, _LINDERA_READY, _LINDERA_ERROR, _LINDERA_DICT_PATH, _LINDERA_DICT_URI
    if _LINDERA_READY:
        return
    with _LINDERA_LOCK:
        if _LINDERA_READY:
            return
        try:
            tag, bundle = _find_tokenizer_bundle()
            extracted = _ensure_wheel_extracted(bundle)
            _add_sys_path(extracted)
            # Also allow using installed packages (engine venv)
            import lindera  # type: ignore
            # Prefer embedded dictionary when available in lindera-python-ipadic
            try:
                dic = lindera.load_dictionary("embedded://ipadic")
                _LINDERA_TOKENIZER = lindera.Tokenizer(dic)
                _LINDERA_DICT_URI = "embedded://ipadic"
            except Exception:
                dict_path = _resolve_dict_path()
                _LINDERA_DICT_PATH = dict_path
                if dict_path:
                    try:
                        try:
                            dic = lindera.load_dictionary(dict_path)
                            _LINDERA_TOKENIZER = lindera.Tokenizer(dic)
                        except Exception:
                            builder = lindera.TokenizerBuilder()
                            builder.set_dictionary(dict_path)
                            _LINDERA_TOKENIZER = builder.build()
                        _LINDERA_DICT_URI = dict_path
                    except Exception as e:
                        _LINDERA_ERROR = f"dictionary load failed: {e}"
                        _LINDERA_TOKENIZER = None
                else:
                    _LINDERA_ERROR = "dictionary not found"
        except Exception as e:
            _LINDERA_ERROR = str(e)
            _LINDERA_TOKENIZER = None
        _LINDERA_READY = True


def lindera_available() -> bool:
    _init_lindera()
    return _LINDERA_TOKENIZER is not None


def lindera_error() -> str:
    _init_lindera()
    return _LINDERA_ERROR


def lindera_dict_uri() -> str:
    _init_lindera()
    return _LINDERA_DICT_URI or _LINDERA_DICT_PATH


def has_cjk(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0x3040 <= code <= 0x30FF
            or 0xAC00 <= code <= 0xD7A3
            or 0x1100 <= code <= 0x11FF
        ):
            return True
    return False


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        (0x4E00 <= code <= 0x9FFF)
        or (0x3400 <= code <= 0x4DBF)
        or (0x3040 <= code <= 0x30FF)
        or (0xAC00 <= code <= 0xD7A3)
        or (0x1100 <= code <= 0x11FF)
    )


def _fallback_cjk_space(text: str) -> str:
    if not text:
        return text
    out = []
    for ch in text:
        if _is_cjk_char(ch):
            if out and out[-1] != " ":
                out.append(" ")
            out.append(ch)
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def cjk_space(text: str) -> str:
    if not text:
        return text
    if not has_cjk(text):
        return " ".join(text.split())
    _init_lindera()
    if _LINDERA_TOKENIZER is None:
        return _fallback_cjk_space(text)
    try:
        tokens = _LINDERA_TOKENIZER.tokenize(text)
        parts = [t.text for t in tokens if getattr(t, "text", None)]
        if not parts:
            return _fallback_cjk_space(text)
        return " ".join(parts)
    except Exception:
        return _fallback_cjk_space(text)
