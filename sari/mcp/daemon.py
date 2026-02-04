import asyncio
import os
import signal
import logging
import ipaddress
import threading
import time
import uuid
from .session import Session

from pathlib import Path
from sari.core.workspace import WorkspaceManager
from sari.core.registry import ServerRegistry

def _resolve_log_dir() -> Path:
    val = (os.environ.get("SARI_LOG_DIR") or "").strip()
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

class SariDaemon:
    def __init__(self):
        self.host = os.environ.get("SARI_DAEMON_HOST", DEFAULT_HOST)
        self.port = int(os.environ.get("SARI_DAEMON_PORT", DEFAULT_PORT))
        self.server = None
        self._loop = None
        self._pinned_workspace_root = None
        self._registry = ServerRegistry()
        self.boot_id = (os.environ.get("SARI_BOOT_ID") or "").strip() or uuid.uuid4().hex
        os.environ["SARI_BOOT_ID"] = self.boot_id
        self._stop_event = threading.Event()
        self._heartbeat_thread = None
        self._idle_since = None
        self._drain_since = None

    def _write_pid(self):
        """Write current PID to file."""
        try:
            pid = os.getpid()
            PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            PID_FILE.write_text(str(pid))
            logger.info(f"Wrote PID {pid} to {PID_FILE}")
        except Exception as e:
            logger.error(f"Failed to write PID file: {e}")

    def _remove_pid(self):
        """Remove PID file."""
        try:
            if PID_FILE.exists():
                current = PID_FILE.read_text().strip()
                if current == str(os.getpid()):
                    PID_FILE.unlink()
                    logger.info("Removed PID file")
        except Exception as e:
            logger.error(f"Failed to remove PID file: {e}")

    def _register_daemon(self):
        try:
            try:
                from sari.version import __version__ as sari_version
            except Exception:
                sari_version = os.environ.get("SARI_VERSION", "dev")
            host = (self.host or DEFAULT_HOST).strip()
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
        val = (os.environ.get("SARI_DAEMON_AUTOSTART") or "").strip().lower()
        if val not in {"1", "true", "yes", "on"}:
            return

        workspace_root = (os.environ.get("SARI_WORKSPACE_ROOT") or "").strip()
        if not workspace_root:
            workspace_root = WorkspaceManager.resolve_workspace_root()

        try:
            from .registry import Registry
            Registry.get_instance().get_or_create(workspace_root)
            self._pinned_workspace_root = workspace_root
            logger.info(f"Auto-started workspace HTTP server for {workspace_root}")
        except Exception as e:
            logger.error(f"Failed to auto-start workspace HTTP server: {e}")

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        try:
            interval = float(os.environ.get("SARI_DAEMON_HEARTBEAT_SEC", "5") or 5)
        except (TypeError, ValueError):
            interval = 5.0
        try:
            idle_sec = float(os.environ.get("SARI_DAEMON_IDLE_SEC", "600") or 600)
        except (TypeError, ValueError):
            idle_sec = 600.0
        try:
            drain_grace = float(os.environ.get("SARI_DAEMON_DRAIN_GRACE_SEC", "10") or 10)
        except (TypeError, ValueError):
            drain_grace = 10.0

        from .registry import Registry
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
                        if active_count == 0:
                            if self._idle_since is None:
                                self._idle_since = now
                            elif now - self._idle_since >= idle_sec:
                                self.shutdown()
                                break
                        else:
                            self._idle_since = None
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")

            self._stop_event.wait(interval)

    async def start(self):
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
            await self.server.serve_forever()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info(f"Accepted connection from {addr}")

        session = Session(reader, writer)
        await session.handle_connection()

        logger.info(f"Closed connection from {addr}")

    def shutdown(self):
        if self._stop_event.is_set():
            return
        self._stop_event.set()

        if self.server:
            try:
                if self._loop:
                    self._loop.call_soon_threadsafe(self.server.close)
                else:
                    self.server.close()
            except Exception:
                pass

        # Shutdown all workspaces to stop indexers and close DBs
        from .registry import Registry
        Registry.get_instance().shutdown_all()

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

    daemon_task = asyncio.create_task(daemon.start())

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
