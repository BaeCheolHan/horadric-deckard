#!/usr/bin/env python3
"""
Entry point for `python -m mcp` execution.

Routes to either:
- CLI mode (sari daemon/proxy commands)
- Legacy server mode (for backward compatibility)
"""
import sys

if __name__ == "__main__":
    # Check if running as CLI
    if len(sys.argv) > 1 and sys.argv[1] in ("daemon", "proxy"):
        from .cli import main
        sys.exit(main())
    else:
        # Legacy: Run as stdio MCP server
        from .server import main
        main()
