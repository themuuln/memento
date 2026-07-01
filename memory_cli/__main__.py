from __future__ import annotations
"""python3 -m memory_cli entry point."""

import sys
from memory_cli.cli import main as _cli_main


def main() -> int:
    """Entry point for console_scripts."""
    return _cli_main()


if __name__ == "__main__":
    sys.exit(main())
