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

# Tail of a node output line, after the [node-N] prefix:
#   [LEVEL] [timestamp] [logger_name]: message
# group 1 = "[LEVEL]" (with any surrounding ANSI, e.g. RCUTILS_COLORIZED_OUTPUT)
# group 2 = " [timestamp]"
# group 3 = " [logger_name]"
# group 4 = ": message" (rest of the line, including trailing newline)
_METADATA_RE = re.compile(
    r'^(\s*(?:\033\[[0-9;]*m)*\[(?:INFO|WARN(?:ING)?|ERROR|DEBUG|FATAL)\](?:\033\[[0-9;]*m)*)'
    r'(\s*\[[^\]]*\])'
    r'(\s*\[[^\]]*\])'
    r'(:.*)$',
    re.DOTALL,
)


def strip_log_metadata(line, prefix_end, show_timestamp=True, show_logger_name=True):
    """Remove the [timestamp] and/or [logger_name] brackets from a node log line's tail.

    `prefix_end` is the index just past the [node-N] prefix (PREFIX_RE.match(line).end()).
    Lines whose tail doesn't match the expected "[LEVEL] [ts] [logger]: msg" shape
    (e.g. traceback continuation lines) are returned unchanged.
    """
    if show_timestamp and show_logger_name:
        return line
    prefix = line[:prefix_end]
    m = _METADATA_RE.match(line[prefix_end:])
    if not m:
        return line
    level_part, ts_part, logger_part, colon_rest = m.groups()
    new_tail = level_part
    if show_timestamp:
        new_tail += ts_part
    if show_logger_name:
        new_tail += logger_part
    return prefix + new_tail + colon_rest


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
