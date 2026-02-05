import os
import sys
import threading
from pathlib import Path
from typing import Optional

_LINDERA_LOCK = threading.Lock()
_LINDERA_TOKENIZER = None
_LINDERA_ERROR = ""
_LINDERA_DICT_PATH = ""
_LINDERA_DICT_URI = ""
_LINDERA_READY = False


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
            # Usually the dictionary files are in the package directory
            return str(mod_path.parent)
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
            # Try to import installed lindera package
            import lindera  # type: ignore

            # Prefer embedded dictionary when available in lindera-python-ipadic
            try:
                # Some versions/forks support embedded://ipadic
                dic = lindera.load_dictionary("embedded://ipadic")
                _LINDERA_TOKENIZER = lindera.Tokenizer(dic)
                _LINDERA_DICT_URI = "embedded://ipadic"
            except Exception:
                # Fallback to loading from dictionary path
                dict_path = _resolve_dict_path()
                _LINDERA_DICT_PATH = dict_path
                if dict_path:
                    try:
                        try:
                            dic = lindera.load_dictionary(dict_path)
                            _LINDERA_TOKENIZER = lindera.Tokenizer(dic)
                        except Exception:
                            # Try builder pattern if direct load fails
                            builder = lindera.TokenizerBuilder()
                            builder.set_dictionary(dict_path)
                            _LINDERA_TOKENIZER = builder.build()
                        _LINDERA_DICT_URI = dict_path
                    except Exception as e:
                        _LINDERA_ERROR = f"dictionary load failed: {e}"
                        _LINDERA_TOKENIZER = None
                else:
                    _LINDERA_ERROR = "dictionary not found (install lindera-dictionary-ipadic)"
        except ImportError:
             _LINDERA_ERROR = "lindera package not installed"
             _LINDERA_TOKENIZER = None
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
