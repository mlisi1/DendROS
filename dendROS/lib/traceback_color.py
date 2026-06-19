"""Traceback colorization state machine."""

import re

_TB_START_RE  = re.compile(r'^Traceback \(most recent call last\):\s*$')
_TB_DURING_RE = re.compile(r'^During handling of the above exception')

_in_traceback   = False
_traceback_color = 'fancy'   # 'fancy' | 'red' | 'off'


def set_mode(mode):
    """Set the traceback colorization mode. Called once at pipe startup."""
    global _traceback_color
    _traceback_color = mode


def reset():
    """Reset _in_traceback state (used in tests to isolate test cases)."""
    global _in_traceback
    _in_traceback = False


def colorize_traceback(content, prefix=''):
    """Colorize one traceback line; updates _in_traceback state.

    content: the traceback text (bare line, or content after the node-prefix separator space)
    prefix:  pre-rendered dim node-prefix to prepend (empty for bare tracebacks)
    Modes controlled by _traceback_color:
      'fancy' — bold red header/exception, dim red frames
      'red'   — all bold red
      'off'   — passthrough, no color, no state tracking
    """
    global _in_traceback
    if _traceback_color == 'off':
        return prefix + content if prefix else content
    stripped = content.rstrip('\n')
    if _in_traceback:
        if stripped == '':
            _in_traceback = False
            return '\n'
        if stripped.startswith('  ') or _TB_START_RE.match(content) or _TB_DURING_RE.match(content):
            frame_color = '\033[31;2m' if _traceback_color == 'fancy' else '\033[31;1m'
            return f'{prefix}{frame_color}{stripped}\033[0m\n'
        _in_traceback = False
        return f'{prefix}\033[31;1m{stripped}\033[0m\n'
    if _TB_START_RE.match(content) or _TB_DURING_RE.match(content):
        _in_traceback = True
        return f'{prefix}\033[31;1m{stripped}\033[0m\n'
    return prefix + content if prefix else content
