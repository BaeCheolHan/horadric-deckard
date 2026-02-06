import asyncio
import inspect
import os
import sys
import signal
import logging
import ipaddress
import threading
import time
import uuid
from pathlib import Path

# Ensure project root is in sys.path
SCRIPT_DIR = Path(__file__).parent
# Go up 3 levels: sari/mcp/daemon.py -> mcp/ -> sari/ -> (repo root)
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sari.mcp.session import Session
from sari.core.workspace import WorkspaceManager
from sari.core.server_registry import ServerRegistry
from sari.core.settings import settings

def _resolve_log_dir() -> Path:
    val = settings.LOG_DIR
    if val:
        return Path(os.path.expanduser(val)).resolve()
    return WorkspaceManager.get_global_log_dir()

def _init_logging() -> None:
    log_dir = _resolve_log_dir()
    handlers = [logging.StreamHandler()]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.insert(0, logging.FileHandler(log_dir / "daemon.log"))
    except Exception:
        # Fall back to /tmp if the default log dir is not writable.
        try:
            tmp_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "sari"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            handlers.insert(0, logging.FileHandler(tmp_dir / "daemon.log"))
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers,
    )

_init_logging()
logger = logging.getLogger("mcp-daemon")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47779
PID_FILE = WorkspaceManager.get_global_data_dir() / "daemon.pid"

def _pid_file() -> Path:
    try:
        if isinstance(PID_FILE, Path):
            return PID_FILE
    except Exception:
        pass
    return WorkspaceManager.get_global_data_dir() / "daemon.pid"

class SariDaemon:
    def __init__(self, host: str = None, port: int = None):
        self.host = host or settings.DAEMON_HOST
        self.port = int(port or settings.DAEMON_PORT)
        self.server = None
        self._loop = None
        self._pinned_workspace_root = None
        self._registry = ServerRegistry()
        
        # Use existing boot ID if provided, otherwise generate new
        env_boot_id = (os.environ.get("SARI_BOOT_ID") or "").strip()
        self.boot_id = env_boot_id or uuid.uuid4().hex
        if not env_boot_id:
            os.environ["SARI_BOOT_ID"] = self.boot_id
            
        self._stop_event = threading.Event()
        self._heartbeat_thread = None
        self._idle_since = None
        self._drain_since = None

    def _write_pid(self):
        """Write current PID to file, ensuring no other daemon is active."""
        try:
            pid_file = _pid_file()
            if pid_file.exists():
                try:
                    old_pid = int(pid_file.read_text().strip())
                    if old_pid != os.getpid():
                        try:
                            os.kill(old_pid, 0)
                            logger.error(f"Daemon already running with PID {old_pid}")
                            sys.exit(1)
                        except OSError:
                            # Process not found, we can take over
                            logger.info(f"Removing stale PID file for {old_pid}")
                            pid_file.unlink()
                except (ValueError, OSError):
                    pass
            
            pid = os.getpid()
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(pid))
            logger.info(f"Wrote PID {pid} to {pid_file}")
        except Exception as e:
            if isinstance(e, SystemExit): raise
            logger.error(f"Failed to write PID file: {e}")

    def _remove_pid(self):
        """Remove PID file."""
        try:
            pid_file = _pid_file()
            if pid_file.exists():
                current = pid_file.read_text().strip()
                if current == str(os.getpid()):
                    pid_file.unlink()
                    logger.info("Removed PID file")
        except Exception as e:
            logger.error(f"Failed to remove PID file: {e}")

    def _register_daemon(self):
        try:
            sari_version = settings.VERSION
            host = (self.host or "127.0.0.1").strip()
            port = int(self.port)
            pid = os.getpid()
            self._registry.register_daemon(self.boot_id, host, port, pid, version=sari_version)
            logger.info(f"Registered daemon {self.boot_id} on {host}:{port}")
        except Exception as e:
            logger.error(f"Failed to register daemon: {e}")

    def _unregister_daemon(self):
        try:
            self._registry.unregister_daemon(self.boot_id)
            logger.info(f"Unregistered daemon {self.boot_id}")
        except Exception as e:
            logger.error(f"Failed to unregister daemon: {e}")

    def _autostart_workspace(self) -> None:
        if not settings.DAEMON_AUTOSTART:
            return

        workspace_root = settings.WORKSPACE_ROOT or WorkspaceManager.resolve_workspace_root()

        try:
            from sari.mcp.workspace_registry import Registry
            Registry.get_instance().get_or_create(workspace_root, persistent=True)
            self._pinned_workspace_root = workspace_root
            logger.info(f"Auto-started workspace HTTP server for {workspace_root}")
        except Exception as e:
            logger.error(f"Failed to auto-start workspace HTTP server: {e}")
        try:
            # Record workspace mapping even if warm-up failed.
            self._registry.set_workspace(workspace_root, self.boot_id)
        except Exception as e:
            logger.error(f"Failed to record workspace mapping: {e}")

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        interval = settings.DAEMON_HEARTBEAT_SEC
        idle_sec = settings.DAEMON_IDLE_SEC
        idle_with_active = settings.DAEMON_IDLE_WITH_ACTIVE
        drain_grace = settings.DAEMON_DRAIN_GRACE_SEC

        from sari.mcp.workspace_registry import Registry
        workspace_registry = Registry.get_instance()

        while not self._stop_event.is_set():
            try:
                self._registry.touch_daemon(self.boot_id)
                daemon_info = self._registry.get_daemon(self.boot_id) or {}
                draining = bool(daemon_info.get("draining"))
                active_count = workspace_registry.active_count()
                now = time.time()

                if draining:
                    if self._drain_since is None:
                        self._drain_since = now
                    if active_count == 0:
                        self.shutdown()
                        break
                    if drain_grace > 0 and now - self._drain_since >= drain_grace:
                        self.shutdown()
                        break
                else:
                    self._drain_since = None
                    if idle_sec > 0:
                        if active_count == 0 or idle_with_active:
                            last_activity = workspace_registry.get_last_activity_ts()
                            if last_activity <= 0:
                                last_activity = now
                            if self._idle_since is None:
                                self._idle_since = last_activity
                            # Keep a small grace window to avoid flapping right after startup.
                            if now - last_activity >= (idle_sec + 1.0):
                                self.shutdown()
                                break
                        else:
                            self._idle_since = None
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")

            self._stop_event.wait(interval)

    async def start_async(self):
        host = (self.host or "127.0.0.1").strip()
        try:
            is_loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"

        if not is_loopback:
            raise SystemExit(
                f"sari daemon refused to start: host must be loopback only (127.0.0.1/localhost/::1). got={host}. "
                "Remote access is NOT supported for security."
            )

        self._write_pid()
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        os.environ["SARI_DAEMON_HOST"] = host
        os.environ["SARI_DAEMON_PORT"] = str(self.port)
        self._loop = asyncio.get_running_loop()
        self._register_daemon()
        self._autostart_workspace()
        self._start_heartbeat()

        addr = self.server.sockets[0].getsockname()
        logger.info(f"Sari Daemon serving on {addr}")

        async with self.server:
            runner = self.server.serve_forever()
            if inspect.isawaitable(runner):
                await runner
            else:
                # Test doubles may provide non-awaitable mocks.
                while not self._stop_event.is_set():
                    await asyncio.sleep(0.1)

    def start(self):
        try:
            asyncio.get_running_loop()
            return self.start_async()
        except RuntimeError:
            try:
                asyncio.run(self.start_async())
            except asyncio.CancelledError:
                pass
            return None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info(f"Accepted connection from {addr}")

        session = Session(reader, writer)
        await session.handle_connection()

        logger.info(f"Closed connection from {addr}")

    def stop(self):
        """Public stop method for external control (tests, etc.)."""
        self.shutdown()

    def shutdown(self):
        if self._stop_event.is_set():
            return
        self._stop_event.set()

        if self.server:
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(self.server.close)
                else:
                    self.server.close()
            except Exception as e:
                logger.debug(f"Error during server close: {e}")

        # Shutdown all workspaces to stop indexers and close DBs
        from sari.mcp.workspace_registry import Registry
        try:
            Registry.get_instance().shutdown_all()
        except Exception:
            pass

        self._unregister_daemon()
        self._remove_pid()

async def main():
    daemon = SariDaemon()

    # Handle signals
    loop = asyncio.get_running_loop()
    stop = asyncio.Future()

    def _handle_signal():
        stop.set_result(None)

    loop.add_signal_handler(signal.SIGTERM, _handle_signal)
    loop.add_signal_handler(signal.SIGINT, _handle_signal)

    daemon_task = asyncio.create_task(daemon.start_async())

    logger.info("Daemon started. Press Ctrl+C to stop.")

    try:
        await stop
    finally:
        logger.info("Stopping daemon...")
        daemon.shutdown()
        # Wait for server to close? asyncio.start_server manages this in async with
        # but we created a task.
        # Actually server.serve_forever() runs until cancelled.
        daemon_task.cancel()
        try:
            await daemon_task
        except asyncio.CancelledError:
            pass
        logger.info("Daemon stopped.")

if __name__ == "__main__":
    asyncio.run(main())
