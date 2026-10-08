#!/usr/bin/env python3
"""`dendros reopen`: reopen this terminal's last `ros2 launch` TUI run, read-only.

The run is saved by lib/launch_tui.py's run_tui() when it ends (lib/tui_history.py);
"this terminal" = DENDROS_SHELL_PID, set by dendROS.sh's dendros() to the shell's `$$`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.colors import DENDROS_TAG
from lib.tui_history import load_last_run


def main():
    last_run = load_last_run()
    if last_run is None:
        print(f'{DENDROS_TAG} no saved TUI run for this terminal '
              f'(needs launch_mode: tui and a finished ros2 launch here)', file=sys.stderr)
        return 1
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f'{DENDROS_TAG} dendros reopen needs an interactive terminal', file=sys.stderr)
        return 1
    try:
        from lib.launch_tui_review import review_tui
    except Exception as e:
        print(f'{DENDROS_TAG} TUI unavailable ({e})', file=sys.stderr)
        return 1
    try:
        review_tui(last_run)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
