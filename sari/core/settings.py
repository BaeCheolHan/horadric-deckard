import os
from typing import Any, Optional, List

def _get_env_any(key: str, default: Any = None) -> Any:
    """Helper to check SARI_ prefix, then raw key, then legacy keys."""
    # 1. SARI_ prefix (Highest priority)
    val = os.environ.get(f"SARI_{key}")
    if val is not None: return val
    
    # 2. Raw key (e.g. PORT, HTTP_PORT)
    val = os.environ.get(key)
    if val is not None: return val
    
    # 3. Specific legacy overrides
    if key == "DAEMON_PORT":
        for legacy in ["PORT", "PORT_OVERRIDE", "DAEMON_PORT"]:
            v = os.environ.get(legacy)
            if v is not None: return v
    elif key == "HTTP_API_PORT":
        for legacy in ["HTTP_PORT", "HTTP_API_PORT"]:
            v = os.environ.get(legacy)
            if v is not None: return v
            
    return default

def _get_bool(key: str, default: bool = False) -> bool:
    val = str(_get_env_any(key, default)).lower()
    return val in {"1", "true", "yes", "on"}

def _get_int(key: str, default: int) -> int:
    try:
        val = _get_env_any(key)
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def _get_float(key: str, default: float) -> float:
    try:
        val = _get_env_any(key)
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default

class Settings:
    """
    Centralized settings manager for Sari.
    Always reads from os.environ to support dynamic changes in tests.
    """
    
    @staticmethod
    def get_env(key: str, default: Any = None) -> Any: return _get_env_any(key, default)
    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool: return _get_bool(key, default)
    @staticmethod
    def get_int(key: str, default: int) -> int: return _get_int(key, default)
    @staticmethod
    def get_float(key: str, default: float) -> float: return _get_float(key, default)

    @property
    def VERSION(self) -> str: return _get_env_any("VERSION", "dev")
    @property
    def LOG_LEVEL(self) -> str: return _get_env_any("LOG_LEVEL", "INFO").upper()
    @property
    def WORKSPACE_ROOT(self) -> Optional[str]: return _get_env_any("WORKSPACE_ROOT")
    @property
    def CONFIG_PATH(self) -> Optional[str]: return _get_env_any("CONFIG")
    @property
    def DATA_DIR(self) -> Optional[str]: return _get_env_any("DATA_DIR")
    @property
    def LOG_DIR(self) -> Optional[str]: return _get_env_any("LOG_DIR")
    @property
    def REGISTRY_FILE(self) -> Optional[str]: return _get_env_any("REGISTRY_FILE")
    @property
    def PERSIST_PATHS(self) -> bool: return _get_bool("PERSIST_PATHS", False) or _get_bool("PERSIST_ROOTS", False)
    @property
    def KEEP_NESTED_ROOTS(self) -> bool: return _get_bool("KEEP_NESTED_ROOTS", False)
    @property
    def ENGINE_MODE(self) -> str: return _get_env_any("ENGINE_MODE", "embedded").strip().lower()
    @property
    def ENGINE_AUTO_INSTALL(self) -> bool: return _get_bool("ENGINE_AUTO_INSTALL", True)
    @property
    def ENGINE_TOKENIZER(self) -> str: return _get_env_any("ENGINE_TOKENIZER", "auto").strip().lower()
    @property
    def LINDERA_DICT_PATH(self) -> str: return _get_env_any("LINDERA_DICT_PATH", "").strip()
    @property
    def SEARCH_FIRST_MODE(self) -> str: return _get_env_any("SEARCH_FIRST_MODE", "warn").strip().lower()
    @property
    def MANUAL_ONLY(self) -> bool: return _get_bool("MANUAL_ONLY", True)
    @property
    def ENGINE_MAX_DOC_BYTES(self) -> int: return _get_int("ENGINE_MAX_DOC_BYTES", 4 * 1024 * 1024)
    @property
    def ENGINE_PREVIEW_BYTES(self) -> int: return _get_int("ENGINE_PREVIEW_BYTES", 8192)
    @property
    def ENGINE_SUGGEST_FILES(self) -> int: return _get_int("ENGINE_SUGGEST_FILES", 10000)
    @property
    def ENGINE_INDEX_MEM_MB(self) -> int: return _get_int("ENGINE_INDEX_MEM_MB", 128)
    @property
    def ENGINE_INDEX_POLICY(self) -> str: return _get_env_any("ENGINE_INDEX_POLICY", "global").strip().lower()
    @property
    def FOLLOW_SYMLINKS(self) -> bool: return _get_bool("FOLLOW_SYMLINKS", False)
    @property
    def MAX_PARSE_BYTES(self) -> int: return _get_int("MAX_PARSE_BYTES", 16 * 1024 * 1024)
    @property
    def MAX_AST_BYTES(self) -> int: return _get_int("MAX_AST_BYTES", 8 * 1024 * 1024)
    @property
    def AST_CACHE_ENTRIES(self) -> int: return _get_int("AST_CACHE_ENTRIES", 128)
    @property
    def INDEX_MEM_MB(self) -> int: return _get_int("INDEX_MEM_MB", 0)
    @property
    def INDEX_WORKERS(self) -> int: return _get_int("INDEX_WORKERS", 2)
    @property
    def SIZE_PROFILE(self) -> str: return _get_env_any("SIZE_PROFILE", "default").strip().lower()
    @property
    def COALESCE_SHARDS(self) -> int: return _get_int("COALESCE_SHARDS", 16)
    @property
    def PARSE_TIMEOUT_SECONDS(self) -> float: return _get_float("PARSE_TIMEOUT_SECONDS", 0.0)
    @property
    def PARSE_TIMEOUT_WORKERS(self) -> int: return _get_int("PARSE_TIMEOUT_WORKERS", 2)
    @property
    def DLQ_POLL_SECONDS(self) -> float: return _get_float("DLQ_POLL_SECONDS", 60.0)
    @property
    def GIT_CHECKOUT_DEBOUNCE(self) -> float: return _get_float("GIT_CHECKOUT_DEBOUNCE", 3.0)
    @property
    def WATCHER_MONITOR_SECONDS(self) -> float: return _get_float("WATCHER_MONITOR_SECONDS", 10.0)
    @property
    def UTF8_DECODE_POLICY(self) -> str: return _get_env_any("UTF8_DECODE_POLICY", "strong").strip().lower()
    @property
    def PURGE_LEGACY_PATHS(self) -> bool: return _get_bool("PURGE_LEGACY_PATHS", False)
    @property
    def EXCLUDE_APPLIES_TO_PARSE(self) -> bool: return _get_bool("EXCLUDE_APPLIES_TO_PARSE", True)
    @property
    def EXCLUDE_APPLIES_TO_AST(self) -> bool: return _get_bool("EXCLUDE_APPLIES_TO_AST", True)
    @property
    def EXCLUDE_APPLIES_TO_META(self) -> bool: return _get_bool("EXCLUDE_APPLIES_TO_META", True)
    @property
    def SAMPLE_LARGE_FILES(self) -> bool: return _get_bool("SAMPLE_LARGE_FILES", False)
    @property
    def DAEMON_HOST(self) -> str: return _get_env_any("DAEMON_HOST", "127.0.0.1")
    @property
    def DAEMON_PORT(self) -> int: return _get_int("DAEMON_PORT", 47779)
    @property
    def HTTP_API_PORT(self) -> int: return _get_int("HTTP_API_PORT", 47777)
    @property
    def ALLOW_NON_LOOPBACK(self) -> bool: return _get_bool("ALLOW_NON_LOOPBACK", False)
    @property
    def DAEMON_IDLE_SEC(self) -> float: return _get_float("DAEMON_IDLE_SEC", 600.0)
    @property
    def DAEMON_IDLE_WITH_ACTIVE(self) -> bool: return _get_bool("DAEMON_IDLE_WITH_ACTIVE", False)
    @property
    def DAEMON_DRAIN_GRACE_SEC(self) -> float: return _get_float("DAEMON_DRAIN_GRACE_SEC", 10.0)
    @property
    def DAEMON_HEARTBEAT_SEC(self) -> float: return _get_float("DAEMON_HEARTBEAT_SEC", 5.0)
    @property
    def DAEMON_AUTOSTART(self) -> bool: return _get_bool("DAEMON_AUTOSTART", False)
    @property
    def RESPONSE_COMPACT(self) -> bool: return _get_bool("RESPONSE_COMPACT", True)
    @property
    def FORMAT(self) -> str: return _get_env_any("FORMAT", "pack").strip().lower()
    @property
    def STORE_CONTENT(self) -> bool: return _get_bool("STORE_CONTENT", True)
    @property
    def STORE_CONTENT_COMPRESS(self) -> bool: return _get_bool("STORE_CONTENT_COMPRESS", False)
    @property
    def STORE_CONTENT_COMPRESS_LEVEL(self) -> int: return _get_int("STORE_CONTENT_COMPRESS_LEVEL", 3)
    @property
    def ENABLE_FTS(self) -> bool: return _get_bool("ENABLE_FTS", False)
    @property
    def ENGINE_RELOAD_MS(self) -> int: return _get_int("ENGINE_RELOAD_MS", 1000)
    @property
    def SNIPPET_MAX_BYTES(self) -> int: return _get_int("SNIPPET_MAX_BYTES", 200000)
    @property
    def SNIPPET_CACHE_SIZE(self) -> int: return _get_int("SNIPPET_CACHE_SIZE", 128)
    @property
    def FTS_REBUILD_ON_START(self) -> bool: return _get_bool("FTS_REBUILD_ON_START", False)
    @property
    def HTTP_LOG_ENABLED(self) -> bool: return _get_bool("HTTP_LOG_ENABLED", True)
    @property
    def FTS_MAX_BYTES(self) -> int: return _get_int("FTS_MAX_BYTES", 1000000)
    @property
    def REGISTRY_IDLE_SEC(self) -> int: return _get_int("REGISTRY_IDLE_SEC", 900)

    @property
    def STORAGE_TTL_DAYS_SNIPPETS(self) -> int: return _get_int("STORAGE_TTL_DAYS_SNIPPETS", 30)
    @property
    def STORAGE_TTL_DAYS_FAILED_TASKS(self) -> int: return _get_int("STORAGE_TTL_DAYS_FAILED_TASKS", 7)
    @property
    def STORAGE_TTL_DAYS_CONTEXTS(self) -> int: return _get_int("STORAGE_TTL_DAYS_CONTEXTS", 30)

    @property
    def GLOBAL_CONFIG_DIR(self) -> str:
        """Global configuration directory: ~/.config/sari"""
        import pathlib
        path = pathlib.Path.home() / ".config" / "sari"
        return str(path)

    @property
    def WORKSPACE_CONFIG_DIR_NAME(self) -> str:
        """Workspace-local configuration directory name: .sari"""
        return ".sari"

settings = Settings()
