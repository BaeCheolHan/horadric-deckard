import threading
import logging
import time
from typing import Dict, Optional, Any
from sari.core.config.manager import ConfigManager
from sari.core.db.main import LocalSearchDB
from sari.core.indexer import Indexer
from sari.core.search_engine import SearchEngine
from sari.core.workspace import WorkspaceManager

logger = logging.getLogger("sari.registry")

class SharedState:
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        try:
            from sari.core.settings import settings
            WorkspaceManager.set_settings(settings)
        except Exception:
            pass
        self.root_id = WorkspaceManager.root_id(workspace_root)
        
        # 1. Load Layered Config (Phase 1)
        self.config_manager = ConfigManager(workspace_root)
        self.config_data = self.config_manager.resolve_final_config()
        
        # 2. Init DB (Phase 4)
        db_path = str(WorkspaceManager.get_global_db_path())
        self.db = LocalSearchDB(db_path)
        try:
            from sari.core.settings import settings
            self.db.set_settings(settings)
        except Exception:
            pass
        
        # 3. Init Indexer (Phase 3 & 2)
        from sari.core.config import Config
        defaults = Config.get_defaults(workspace_root)
        defaults["workspace_roots"] = [workspace_root]
        defaults["include_ext"] = self.config_data.get("final_extensions", defaults["include_ext"])
        defaults["include_files"] = self.config_data.get("final_filenames", defaults["include_files"])
        defaults["exclude_dirs"] = self.config_data.get("final_exclude_dirs", defaults["exclude_dirs"])
        defaults["exclude_globs"] = self.config_data.get("final_exclude_globs", defaults["exclude_globs"])
        defaults["gitignore_lines"] = self.config_data.get("gitignore_lines", defaults.get("gitignore_lines", []))
        cfg_obj = Config(**defaults)
        
        self.indexer = Indexer(cfg_obj, self.db, logger=logger)
        
        # 4. Wire Scheduling Coordinator for Read-Priority
        self.db.coordinator = self.indexer.coordinator
        self.search_engine = SearchEngine(self.db)
        
        # 5. MCP Server instance (Lazy import to avoid circularity)
        from sari.mcp.server import LocalSearchMCPServer
        self.server = LocalSearchMCPServer(workspace_root)
        
        self.last_activity = time.time()
        self.ref_count = 0
        self._lock = threading.Lock()

    def start(self): 
        threading.Thread(target=self.indexer.run_forever, daemon=True).start()
    
    def touch(self):
        with self._lock:
            self.last_activity = time.time()
        
    def stop(self):
        self.indexer.stop()
        try:
            self.db.close_all()
        except Exception:
            try: self.db.close()
            except: pass

class Registry:
    _instance = None
    _lock = threading.Lock()
    def __init__(self): self._sessions: Dict[str, SharedState] = {}
    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None: cls._instance = cls()
            return cls._instance
    def get_or_create(self, workspace_root: str) -> SharedState:
        with self._lock:
            if workspace_root not in self._sessions:
                session = SharedState(workspace_root)
                session.start()
                self._sessions[workspace_root] = session
            self._sessions[workspace_root].ref_count += 1
            self._sessions[workspace_root].touch()
            return self._sessions[workspace_root]
            
    def touch_workspace(self, workspace_root: str):
        with self._lock:
            if workspace_root in self._sessions:
                self._sessions[workspace_root].touch()
                
    def release(self, workspace_root: str):
        with self._lock:
            if workspace_root in self._sessions:
                state = self._sessions[workspace_root]
                state.ref_count = max(0, state.ref_count - 1)
                state.touch()
                if state.ref_count == 0:
                    state.stop()
                    del self._sessions[workspace_root]

    def shutdown_all(self):
        with self._lock:
            for s in self._sessions.values(): s.stop()
            self._sessions.clear()
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.ref_count > 0)
    def get_last_activity_ts(self) -> float: 
        with self._lock:
            return max((s.last_activity for s in self._sessions.values() if s.ref_count > 0), default=0.0)
