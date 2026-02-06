#!/usr/bin/env python3
"""
Runner for Shopping Browser skill scripts.
Uses stealth-browser's virtual environment (shared dependency).
"""

import os
import sys
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
STEALTH_DIR = Path.home() / ".claude" / "skills" / "stealth-browser"


def get_venv_python():
    """Get Python from stealth-browser's venv."""
    venv_python = STEALTH_DIR / ".venv" / "bin" / "python"
    if not venv_python.exists():
        print("Error: stealth-browser venv not found.", file=sys.stderr)
        print("Run: cd ~/.claude/skills/stealth-browser && python3 scripts/setup_environment.py", file=sys.stderr)
        sys.exit(1)
    return venv_python


def main():
    if len(sys.argv) < 2:
        print("Usage: python run.py <site> <command> [args...]")
        print("       python run.py track <site> <product_id>")
        print("       python run.py pool start|stop|status")
        print("\nSites: amazon, newegg")
        print("\nCommands:")
        print("  search <query>             - Search products")
        print("  check-price <ID>           - Get price/availability")
        print("  product <ID>               - Full product details")
        print("  add-to-cart <ID>           - Add to cart")
        print("  cart                       - View cart")
        print("  my-orders                  - Recent orders")
        print("\nTracking:")
        print("  track <site> <ID>          - Start tracking")
        print("  untrack <site> <ID>        - Stop tracking")
        print("  history <site> <ID>        - Price history")
        print("  alerts                     - Pending alerts")
        print("  check-all                  - Refresh all tracked")
        print("\nPool:")
        print("  pool start|stop|status     - Session pool management")
        sys.exit(1)

    venv_python = get_venv_python()
    cli_script = SKILL_DIR / "scripts" / "cli.py"

    cmd = [str(venv_python), str(cli_script)] + sys.argv[1:]

    try:
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
