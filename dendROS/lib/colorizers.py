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


def colorize_tag_only(line, ansi_code, label, show_tag, tag_position='after', tag_style='normal'):
    """Color only the [node-N] prefix and optional [TAG] badge."""
    m = PREFIX_RE.match(line)
    if not m:
        return line
    prefix = line[:m.end()]
    rest = line[m.end():]
    colored_prefix = _ansi(ansi_code) + prefix + RESET
    if show_tag and label:
        tag_ansi = _ansi(ansi_code + ';7') if tag_style == 'inverted' else _ansi(ansi_code)
        if tag_position == 'before':
            return tag_ansi + f'[{label}]' + RESET + ' ' + colored_prefix + rest
        return colored_prefix + tag_ansi + f' [{label}]' + RESET + rest
    return colored_prefix + rest


def colorize_full_line(line, ansi_code, label=None, show_tag=False, tag_position='after', tag_style='normal'):
    """Color the entire line, optionally inserting a [TAG] badge.

    Strips any embedded ANSI codes first so inner resets don't cancel the outer color.
    In inverted mode the badge gets its own escape (colored background, default text)
    while the rest of the line uses the normal foreground color.
    """
    clean = _ANSI_RE.sub('', line.rstrip('\n'))
    if show_tag and label:
        m = PREFIX_RE.match(clean)
        if m:
            if tag_style == 'inverted':
                tag_seq = _ansi(ansi_code + ';7') + f'[{label}]' + RESET
                if tag_position == 'before':
                    return tag_seq + ' ' + _ansi(ansi_code) + clean + RESET + '\n'
                before = clean[:m.end()]
                after = clean[m.end():]
                return _ansi(ansi_code) + before + RESET + ' ' + tag_seq + _ansi(ansi_code) + after + RESET + '\n'
            else:
                if tag_position == 'before':
                    clean = f'[{label}] ' + clean
                else:
                    clean = clean[:m.end()] + f' [{label}]' + clean[m.end():]
    return _ansi(ansi_code) + clean + RESET + '\n'


def colorize_line(line, ansi_code, label, show_tag, color_mode, tag_position='after', tag_style='normal'):
    if color_mode == 'full_line':
        return colorize_full_line(line, ansi_code, label, show_tag, tag_position, tag_style)
    return colorize_tag_only(line, ansi_code, label, show_tag, tag_position, tag_style)


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
