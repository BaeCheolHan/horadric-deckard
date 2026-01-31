import asyncio
import os
import signal
import logging
from .session import Session

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp-daemon")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47779

class DeckardDaemon:
    def __init__(self):
        self.host = os.environ.get("DECKARD_DAEMON_HOST", DEFAULT_HOST)
        self.port = int(os.environ.get("DECKARD_DAEMON_PORT", DEFAULT_PORT))
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        
        addr = self.server.sockets[0].getsockname()
        logger.info(f"Deckard Daemon serving on {addr}")

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

async def main():
    daemon = DeckardDaemon()
    
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
