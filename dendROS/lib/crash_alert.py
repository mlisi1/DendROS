"""Crash alert: node death detection and periodic inline banner."""

import re
import sys
import time

from lib.colorizers import _LOG_LEVELS

_DIED_LAUNCH_RE = re.compile(
    r'^\[(?:INFO|WARN(?:ING)?|ERROR|DEBUG|FATAL)\]\s+'
    r'\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\].*?\bprocess has died\b'
)
_DIED_RE = re.compile(
    r'^\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\].*?\bprocess has died\b'
)
_EXIT_CODE_RE = re.compile(r'\bexit code:?\s+(-?\d+)')
_EXIT_NONZERO_RE = re.compile(
    r'^\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\].*?\bprocess exited with return code:\s*(-?\d+)'
)

_crash_alert_enabled  = False
_crash_alert_color    = 'node'
_crash_alert_interval = 30.0
_dead_nodes           = []   # each entry: (node_name, exit_code_str_or_None, ansi_code_or_None)
_last_alert_time      = 0.0


def setup(enabled, color, interval):
    """Configure crash alert at pipe startup."""
    global _crash_alert_enabled, _crash_alert_color, _crash_alert_interval
    _crash_alert_enabled  = enabled
    _crash_alert_color    = color
    _crash_alert_interval = interval


def detect_death(line):
    """Return (node_name, exit_code) if line signals unexpected node death.

    Handles two line formats:
      Launch-framework: [LEVEL] [node-N]: process has died [pid X, exit code Y]
      Node output:      [node-N]: process has died [pid X, exit code Y]
    Also catches non-zero "process exited with return code: N".
    Returns (None, None) when no death is detected.
    """
    m = _DIED_LAUNCH_RE.match(line)
    if m:
        ec_m = _EXIT_CODE_RE.search(line)
        return m.group(1), (ec_m.group(1) if ec_m else None)
    m = _DIED_RE.match(line)
    if m and m.group(1) not in _LOG_LEVELS:
        ec_m = _EXIT_CODE_RE.search(line)
        return m.group(1), (ec_m.group(1) if ec_m else None)
    m = _EXIT_NONZERO_RE.match(line)
    if m and m.group(1) not in _LOG_LEVELS and m.group(2) != '0':
        return m.group(1), m.group(2)
    return None, None


def print_alert_banner():
    """Print a prominent inline alert banner."""
    global _last_alert_time
    if not _dead_nodes:
        return
    HDR = '\033[31;1;7m'
    RED = '\033[31;1m'
    DIM = '\033[2m'
    RST = '\033[0m'

    parts = []
    for node_name, exit_code, node_color in _dead_nodes:
        nc = (f'\033[{node_color}m'
              if _crash_alert_color == 'node' and node_color else RED)
        ec = f' exit {exit_code}' if exit_code is not None else ' (died)'
        parts.append(f'{nc}{node_name}{RST}{DIM}{ec}{RST}')

    nodes = f'{DIM}  ·  {RST}'.join(parts)
    sys.stdout.write(f'{HDR} !! CRASH ALERT {RST}  {nodes}\n')
    sys.stdout.flush()
    _last_alert_time = time.monotonic()
