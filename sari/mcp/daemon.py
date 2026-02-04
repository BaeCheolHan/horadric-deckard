import asyncio
import os
import signal
import logging
import ipaddress
from .session import Session

from pathlib import Path
from sari.core.workspace import WorkspaceManager

def _resolve_log_dir() -> Path:
    val = (os.environ.get("SARI_LOG_DIR") or "").strip()
    if val:
        return Path(os.path.expanduser(val)).resolve()
    return WorkspaceManager.get_global_data_dir()

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
                PID_FILE.unlink()
                logger.info("Removed PID file")
        except Exception as e:
            logger.error(f"Failed to remove PID file: {e}")

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
        if self.server:
            self.server.close()

        # Shutdown all workspaces to stop indexers and close DBs
        from .registry import Registry
        Registry.get_instance().shutdown_all()

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