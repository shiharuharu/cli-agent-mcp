"""CLI Agent MCP 入口点。

支持: python -m cli_agent_mcp
"""

import multiprocessing

from .server import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
