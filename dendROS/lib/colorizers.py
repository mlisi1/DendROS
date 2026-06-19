"""Line colorization functions for DendROS pipe output."""

import re

from lib.colors import _ansi, RESET, _ANSI_RE

# Node output:    [node-N] [INFO] [timestamp] [logger]: message
PREFIX_RE = re.compile(r"^\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\]")

# Launch-framework output: [INFO] [node-N]: message  (level bracket comes first)
LAUNCH_RE = re.compile(
    r"^(\[(?:INFO|WARN(?:ING)?|ERROR|DEBUG|FATAL)\] )(\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\])"
)

_LOG_LEVELS = frozenset({'INFO', 'WARN', 'WARNING', 'ERROR', 'DEBUG', 'FATAL'})


def colorize_tag_only(line, ansi_code, label, show_tag, tag_position='after'):
    """Color only the [node-N] prefix and optional [TAG] badge."""
    m = PREFIX_RE.match(line)
    if not m:
        return line
    prefix = line[:m.end()]
    rest = line[m.end():]
    colored_prefix = _ansi(ansi_code) + prefix + RESET
    if show_tag and label:
        if tag_position == 'before':
            return _ansi(ansi_code) + f'[{label}]' + RESET + ' ' + colored_prefix + rest
        return colored_prefix + _ansi(ansi_code) + f' [{label}]' + RESET + rest
    return colored_prefix + rest


def colorize_full_line(line, ansi_code, label=None, show_tag=False, tag_position='after'):
    """Color the entire line, optionally inserting a [TAG] badge.

    Strips any embedded ANSI codes first so inner resets don't cancel the outer color.
    """
    if show_tag and label:
        m = PREFIX_RE.match(line)
        if m:
            if tag_position == 'before':
                line = f'[{label}] ' + line
            else:
                line = line[:m.end()] + f' [{label}]' + line[m.end():]
    clean = _ANSI_RE.sub('', line.rstrip('\n'))
    return _ansi(ansi_code) + clean + RESET + '\n'


def colorize_line(line, ansi_code, label, show_tag, color_mode, tag_position='after'):
    if color_mode == 'full_line':
        return colorize_full_line(line, ansi_code, label, show_tag, tag_position)
    return colorize_tag_only(line, ansi_code, label, show_tag, tag_position)


def colorize_launch_msg(line, ansi_code, color_mode):
    """Color a launch-framework line ([INFO] [node-N]: ...). No badge — just color the bracket."""
    if color_mode == 'full_line':
        return colorize_full_line(line, ansi_code)
    m = LAUNCH_RE.match(line)
    if not m:
        return line
    level_part = m.group(1)
    bracket    = m.group(2)
    after      = line[m.end():]
    return level_part + _ansi(ansi_code) + bracket + RESET + after
