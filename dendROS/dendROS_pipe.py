#!/usr/bin/env python3
"""DendROS colorizer pipe — reads ros2 output from stdin and colorizes by node group."""

import sys
import os
import re
import subprocess

try:
    import yaml
except ImportError:
    for line in sys.stdin:
        sys.stdout.write(line)
        sys.stdout.flush()
    sys.exit(0)

# Node output:    [node-N] [INFO] [timestamp] [logger]: message
PREFIX_RE = re.compile(r"^\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\]")

# Launch-framework output: [INFO] [node-N]: message  (level bracket comes first)
LAUNCH_RE = re.compile(r"^(\[(?:INFO|WARN(?:ING)?|ERROR|DEBUG|FATAL)\] )(\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\])")

_LOG_LEVELS = frozenset({'INFO', 'WARN', 'WARNING', 'ERROR', 'DEBUG', 'FATAL'})

_DEBUG = os.environ.get('DENDROS_DEBUG', '') not in ('', '0')


def _dbg(msg):
    print(f'\033[35;1m[dendROS]\033[0m {msg}', file=sys.stderr, flush=True)


def extract_package_name(argv):
    """Return the package name from ros2 launch/run argv, skipping flags."""
    for arg in argv[1:]:
        if not arg.startswith('-'):
            return arg
    return None


def find_config(pkg_name):
    """Return path to dendROS.yaml for pkg_name, or None if not found."""
    if not pkg_name:
        return None

    try:
        result = subprocess.run(
            ['ros2', 'pkg', 'prefix', pkg_name],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            prefix = result.stdout.strip()
            candidate = os.path.join(prefix, 'share', pkg_name, 'config', 'dendROS.yaml')
            if os.path.isfile(candidate):
                return candidate
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    for prefix in os.environ.get('AMENT_PREFIX_PATH', '').split(':'):
        if not prefix:
            continue
        candidate = os.path.join(prefix, 'share', pkg_name, 'config', 'dendROS.yaml')
        if os.path.isfile(candidate):
            return candidate

    return None


def load_config(config_path):
    """Parse dendROS.yaml and return (color_map, tag_map, defaults)."""
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    color_map = {}
    tag_map = {}

    for group_name, group in (data.get('groups') or {}).items():
        ansi_code = str(group.get('color', ''))
        label = group.get('label', group_name.upper()[:3])
        for node in (group.get('nodes') or []):
            color_map[node] = ansi_code
            tag_map[node] = label

    defaults = data.get('defaults') or {}
    return color_map, tag_map, defaults


def _ansi(code):
    return f'\033[{code}m'

RESET = '\033[0m'
_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def colorize_tag_only(line, ansi_code, label, show_tag):
    """Color only the [node-N] prefix and optional [TAG] badge."""
    m = PREFIX_RE.match(line)
    if not m:
        return line
    prefix = line[:m.end()]
    rest = line[m.end():]
    colored_prefix = _ansi(ansi_code) + prefix + RESET
    tag_str = (_ansi(ansi_code) + f' [{label}]' + RESET) if (show_tag and label) else ''
    return colored_prefix + tag_str + rest


def colorize_full_line(line, ansi_code, label=None, show_tag=False):
    """Color the entire line, optionally inserting a [TAG] badge after the [node-N] prefix.

    Strips any embedded ANSI codes first so inner resets don't cancel our outer color.
    """
    # Insert badge before stripping so it lands in the right position
    if show_tag and label:
        m = PREFIX_RE.match(line)
        if m:
            line = line[:m.end()] + f' [{label}]' + line[m.end():]
    clean = _ANSI_RE.sub('', line.rstrip('\n'))
    return _ansi(ansi_code) + clean + RESET + '\n'


def colorize_line(line, ansi_code, label, show_tag, color_mode):
    if color_mode == 'full_line':
        return colorize_full_line(line, ansi_code, label, show_tag)
    return colorize_tag_only(line, ansi_code, label, show_tag)


def colorize_launch_msg(line, ansi_code, color_mode):
    """Color a launch-framework line ([INFO] [node-N]: ...). No badge — just color the bracket."""
    if color_mode == 'full_line':
        return colorize_full_line(line, ansi_code)
    m = LAUNCH_RE.match(line)
    if not m:
        return line
    level_part = m.group(1)    # "[INFO] "
    bracket    = m.group(2)    # "[talker-1]"
    after      = line[m.end():]
    return level_part + _ansi(ansi_code) + bracket + RESET + after


def resolve_node(node_name, color_map, tag_map):
    """Return (ansi_code, label) for node_name, trying full name then basename."""
    if node_name in color_map:
        return color_map[node_name], tag_map.get(node_name)
    basename = node_name.rsplit('/', 1)[-1]
    if basename in color_map:
        return color_map[basename], tag_map.get(basename)
    return None, None


def main():
    argv = sys.argv[1:]

    pkg_name = extract_package_name(argv) if argv else None
    config_path = find_config(pkg_name) if pkg_name else None

    color_map, tag_map, defaults = {}, {}, {}
    if config_path:
        try:
            color_map, tag_map, defaults = load_config(config_path)
        except Exception:
            pass

    show_tag = defaults.get('show_group_tag', True)
    color_mode = defaults.get('color_mode', 'tag_only')
    unmatched_color = defaults.get('unmatched_color') or None

    if _DEBUG:
        n_groups = len({v for v in color_map.values()})
        n_nodes  = len(color_map)
        unmatched_desc = unmatched_color if unmatched_color else 'passthrough'
        if config_path:
            _dbg(f'package=\033[1m{pkg_name}\033[0m  '
                 f'mode={color_mode}  show_tag={"on" if show_tag else "off"}  '
                 f'unmatched={unmatched_desc}  '
                 f'{n_groups} group{"s" if n_groups != 1 else ""}, {n_nodes} node{"s" if n_nodes != 1 else ""}')
            _dbg(f'config: {config_path}')
            by_group: dict = {}
            for node, code in color_map.items():
                label = tag_map.get(node, '')
                by_group.setdefault((code, label), []).append(node)
            for (code, label), nodes in by_group.items():
                badge = f' [{label}]' if label else ''
                _dbg(f'  \033[{code}m█\033[0m{badge}  {", ".join(nodes)}')
        else:
            _dbg(f'package=\033[1m{pkg_name}\033[0m  no dendROS.yaml found — passthrough mode')

    try:
        for line in sys.stdin:
            m = PREFIX_RE.match(line)
            if m and m.group(1) not in _LOG_LEVELS:
                # node output format: [node-N] [INFO] ...
                node_name = m.group(1)
                ansi_code, label = resolve_node(node_name, color_map, tag_map)
                if ansi_code is None and unmatched_color:
                    ansi_code = str(unmatched_color)
                    label = None
                if ansi_code:
                    line = colorize_line(line, ansi_code, label, show_tag, color_mode)
            else:
                # launch-framework format: [INFO] [node-N]: ...
                lm = LAUNCH_RE.match(line)
                if lm:
                    node_name = lm.group(3)
                    ansi_code, _ = resolve_node(node_name, color_map, tag_map)
                    if ansi_code is None and unmatched_color:
                        ansi_code = str(unmatched_color)
                    if ansi_code:
                        line = colorize_launch_msg(line, ansi_code, color_mode)

            sys.stdout.write(line)
            sys.stdout.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        pass


if __name__ == '__main__':
    main()
