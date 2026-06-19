#!/usr/bin/env python3
"""DendROS colorizer pipe — reads ros2 output from stdin and colorizes by node group."""

import atexit
import fnmatch
import os
import re
import shutil
import signal
import subprocess
import sys
import time

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

# Launch file include patterns
_PY_INCLUDE_RE = re.compile(
    r'''(?:get_package_share_directory|FindPackageShare)\s*\(\s*['"]([a-zA-Z0-9_.-]+)['"]\s*\)'''
)
_XML_INCLUDE_RE = re.compile(r'\$\(find-pkg-share\s+([a-zA-Z0-9_.-]+)\)')

_LOG_LEVELS = frozenset({'INFO', 'WARN', 'WARNING', 'ERROR', 'DEBUG', 'FATAL'})

_DEBUG = os.environ.get('DENDROS_DEBUG', '') not in ('', '0')

# Crash alert ─────────────────────────────────────────────────────────────────
# Launch-framework format: [LEVEL] [node-N]: process has died [pid X, exit code Y]
_DIED_LAUNCH_RE = re.compile(
    r'^\[(?:INFO|WARN(?:ING)?|ERROR|DEBUG|FATAL)\]\s+'
    r'\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\].*?\bprocess has died\b'
)
# Node-output format: [node-N]: process has died [pid X, exit code Y]
_DIED_RE = re.compile(
    r'^\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\].*?\bprocess has died\b'
)
# Exit code embedded in either "process has died" message: "exit code N" (no colon)
_EXIT_CODE_RE = re.compile(r'\bexit code:?\s+(-?\d+)')
# Non-zero exit via "process exited with return code: N"
_EXIT_NONZERO_RE = re.compile(
    r'^\[([a-zA-Z0-9_./-]+?)(?:-\d+)?\].*?\bprocess exited with return code:\s*(-?\d+)'
)

_crash_alert_enabled  = False
_crash_alert_color    = 'node'
_crash_alert_interval = 30.0   # seconds between periodic reprints; 0 = no reprints
# Each entry: (node_name, exit_code_str_or_None, ansi_code_or_None)
_dead_nodes           = []
_alert_dismissed      = False   # True after 'dendros dismiss'; un-dismiss reprints once
_last_alert_time      = 0.0
_pid_file_path        = None

# Traceback colorization ───────────────────────────────────────────────────────
_TB_START_RE    = re.compile(r'^Traceback \(most recent call last\):\s*$')
_TB_DURING_RE   = re.compile(r'^During handling of the above exception')
_in_traceback   = False
_traceback_color = 'fancy'   # 'fancy' | 'red' | 'off'

# Named color support ─────────────────────────────────────────────────────────
_COLOR_CODES = {
    'black': 30, 'red': 31, 'green': 32, 'yellow': 33,
    'blue':  34, 'magenta': 35, 'cyan': 36, 'white':  37,
}

_HEX_RE = re.compile(r'^(@?)#([0-9a-fA-F]{6})$')


def _hex_to_ansi(hex6, bold=False):
    """Convert a 6-digit hex string to a 24-bit ANSI SGR code string."""
    r = int(hex6[0:2], 16)
    g = int(hex6[2:4], 16)
    b = int(hex6[4:6], 16)
    base = f'38;2;{r};{g};{b}'
    return f'1;{base}' if bold else base


def _resolve_color(value):
    """Convert a color value to an ANSI SGR string.

    Accepts:
      Raw ANSI codes:       "34;1", "92"
      Hex truecolor:        "#FF6600"            (24-bit color, normal)
                            "@#FF6600"           (24-bit color, bold)
                            "bold #FF6600"       (same as @#FF6600)
      Named colors:         "yellow", "light blue", "dark red", "bold green"
                            "bold light cyan"
    """
    s = str(value).strip()
    sl = s.lower()

    # Raw ANSI code (only digits and semicolons)
    if re.match(r'^[0-9;]+$', sl):
        return sl

    # Hex truecolor: @#RRGGBB (bold) or #RRGGBB (normal)
    m = _HEX_RE.match(sl)
    if m:
        return _hex_to_ansi(m.group(2), bold=m.group(1) == '@')

    words = sl.split()
    bold  = 'bold'   in words
    light = 'light'  in words or 'bright' in words
    dark  = 'dark'   in words or 'dim'    in words

    # "bold #RRGGBB" — word-based bold modifier on a hex color
    for word in words:
        m = _HEX_RE.match(word)
        if m:
            return _hex_to_ansi(m.group(2), bold=bold)

    # Named palette color
    base_code = next((_COLOR_CODES[w] for w in words if w in _COLOR_CODES), None)
    if base_code is None:
        return sl  # unrecognized — pass through

    if light:
        parts = [str(base_code + 60)]   # 30+60=90 … 37+60=97 (bright range)
        if bold:
            parts.append('1')
    else:
        parts = [str(base_code)]
        if dark:
            parts.append('2')
        elif bold:
            parts.append('1')

    return ';'.join(parts)


def _dbg(msg):
    print(f'\033[35;1m[dendROS]\033[0m {msg}', file=sys.stderr, flush=True)


# ── Crash alert helpers ───────────────────────────────────────────────────────

def _detect_death(line):
    """Return (node_name, exit_code) if line signals unexpected node death.

    Handles two line formats:
      Launch-framework: [LEVEL] [node-N]: process has died [pid X, exit code Y]
      Node output:      [node-N]: process has died [pid X, exit code Y]
    Also catches non-zero "process exited with return code: N".
    Returns (None, None) when no death is detected.
    """
    # Launch-framework format — must check first so [ERROR]/[INFO] isn't captured as node name
    m = _DIED_LAUNCH_RE.match(line)
    if m:
        ec_m = _EXIT_CODE_RE.search(line)
        return m.group(1), (ec_m.group(1) if ec_m else None)
    # Node-output format — reject if first token is a log level keyword
    m = _DIED_RE.match(line)
    if m and m.group(1) not in _LOG_LEVELS:
        ec_m = _EXIT_CODE_RE.search(line)
        return m.group(1), (ec_m.group(1) if ec_m else None)
    # Non-zero exit code (node-output format only)
    m = _EXIT_NONZERO_RE.match(line)
    if m and m.group(1) not in _LOG_LEVELS and m.group(2) != '0':
        return m.group(1), m.group(2)
    return None, None


def _print_alert_banner():
    """Print a prominent inline alert banner. No-op when dismissed."""
    global _last_alert_time
    if _alert_dismissed or not _dead_nodes:
        return
    # \033[31;1;7m = bold red + reverse-video → red background, terminal-default text
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


def _make_dim(code):
    """Return a dim variant of an ANSI SGR code: strips bold (1), adds dim (2)."""
    parts = [p for p in code.split(';') if p and p != '1']
    if '2' not in parts:
        parts.append('2')
    return ';'.join(parts) if parts else '2'


def _colorize_traceback(content, prefix=''):
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


def _toggle_alert(_sig, _frame):
    """SIGUSR1 handler: dismiss (silence) or un-dismiss the alert."""
    global _alert_dismissed
    _alert_dismissed = not _alert_dismissed
    if not _alert_dismissed and _dead_nodes:
        _print_alert_banner()


def _write_pid_file():
    global _pid_file_path
    try:
        _pid_file_path = f'/tmp/dendros_alert_{os.getppid()}'
        with open(_pid_file_path, 'w') as f:
            f.write(str(os.getpid()))
    except OSError:
        _pid_file_path = None


def _cleanup():
    """Remove PID file on exit."""
    if _pid_file_path:
        try:
            os.unlink(_pid_file_path)
        except OSError:
            pass


def extract_package_name(argv):
    """Return the package name from ros2 launch/run argv, skipping flags."""
    for arg in argv[1:]:
        if not arg.startswith('-'):
            return arg
    return None


def extract_launch_file(argv):
    """Return the launch file name (second non-flag positional) from ros2 launch argv."""
    if not argv or argv[0] != 'launch':
        return None
    positionals = [a for a in argv[1:] if not a.startswith('-')]
    return positionals[1] if len(positionals) >= 2 else None


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


def find_launch_file(pkg_name, launch_file_name):
    """Return path to the launch file for pkg_name, or None if not found."""
    if not pkg_name or not launch_file_name:
        return None

    try:
        result = subprocess.run(
            ['ros2', 'pkg', 'prefix', pkg_name],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            prefix = result.stdout.strip()
            candidate = os.path.join(prefix, 'share', pkg_name, 'launch', launch_file_name)
            if os.path.isfile(candidate):
                return candidate
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    for prefix in os.environ.get('AMENT_PREFIX_PATH', '').split(':'):
        if not prefix:
            continue
        candidate = os.path.join(prefix, 'share', pkg_name, 'launch', launch_file_name)
        if os.path.isfile(candidate):
            return candidate

    return None


def extract_included_packages(launch_file_path):
    """Return package names referenced in a launch file (Python or XML), deduplicated."""
    if not launch_file_path or not os.path.isfile(launch_file_path):
        return []
    try:
        with open(launch_file_path, 'r', errors='replace') as f:
            content = f.read()
    except OSError:
        return []

    ext = os.path.splitext(launch_file_path)[1].lower()
    if ext == '.xml':
        raw = _XML_INCLUDE_RE.findall(content)
    elif ext == '.py':
        raw = _PY_INCLUDE_RE.findall(content)
    else:
        raw = _PY_INCLUDE_RE.findall(content) + _XML_INCLUDE_RE.findall(content)

    seen = set()
    result = []
    for pkg in raw:
        if pkg not in seen:
            seen.add(pkg)
            result.append(pkg)
    return result


def merge_color_maps(primary_color, primary_tag, primary_mode, secondaries):
    """Merge secondary (color_map, tag_map, mode_map) triples into primary.

    Primary wins all node-name conflicts.
    """
    merged_color = dict(primary_color)
    merged_tag   = dict(primary_tag)
    merged_mode  = dict(primary_mode)
    for sec_color, sec_tag, sec_mode in secondaries:
        for node, code in sec_color.items():
            if node not in merged_color:
                merged_color[node] = code
                merged_tag[node]   = sec_tag.get(node)
                if node in sec_mode:
                    merged_mode[node] = sec_mode[node]
    return merged_color, merged_tag, merged_mode


def resolve_node_mode(node_name, mode_map):
    """Return the per-node color_mode override from group-level color_mode:, or None."""
    if not mode_map:
        return None
    if node_name in mode_map:
        return mode_map[node_name]
    basename = node_name.rsplit('/', 1)[-1]
    if basename in mode_map:
        return mode_map[basename]
    for pattern, mode in mode_map.items():
        if fnmatch.fnmatch(node_name, pattern):
            return mode
    for pattern, mode in mode_map.items():
        if fnmatch.fnmatch(basename, pattern):
            return mode
    return None


def load_config(config_path):
    """Parse dendROS.yaml and return (color_map, tag_map, mode_map, defaults).

    mode_map holds per-node color_mode overrides set via group-level color_mode:.
    tag_map stores None for nodes whose group has show_tag: false.
    """
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    color_map = {}
    tag_map   = {}
    mode_map  = {}

    for group_name, group in (data.get('groups') or {}).items():
        ansi_code   = _resolve_color(group.get('color', ''))
        label       = group.get('label', '')
        group_mode  = group.get('color_mode')   # None → use global/package default
        if group.get('show_tag') is False:
            label = None                         # suppress badge for this group
        for node in (group.get('nodes') or []):
            color_map[node] = ansi_code
            tag_map[node]   = label
            if group_mode is not None:
                mode_map[node] = group_mode

    defaults = data.get('defaults') or {}
    return color_map, tag_map, mode_map, defaults


def _ansi(code):
    return f'\033[{code}m'

RESET = '\033[0m'
_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


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

    Strips any embedded ANSI codes first so inner resets don't cancel our outer color.
    """
    # Insert badge before stripping so it lands in the right position
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
    level_part = m.group(1)    # "[INFO] "
    bracket    = m.group(2)    # "[talker-1]"
    after      = line[m.end():]
    return level_part + _ansi(ansi_code) + bracket + RESET + after


def resolve_node(node_name, color_map, tag_map):
    """Return (ansi_code, label) for node_name.

    Lookup order:
      1. Exact full-path match  (/ns/talker  vs  /ns/talker)
      2. Exact basename match   (/ns/talker  vs  talker)
      3. Wildcard full-path     (/ns/talker  vs  /ns/talk*)
      4. Wildcard basename      (/ns/talker  vs  talk*)
    First matching pattern wins.
    """
    if node_name in color_map:
        return color_map[node_name], tag_map.get(node_name)
    basename = node_name.rsplit('/', 1)[-1]
    if basename in color_map:
        return color_map[basename], tag_map.get(basename)
    for pattern, code in color_map.items():
        if fnmatch.fnmatch(node_name, pattern):
            return code, tag_map.get(pattern)
    for pattern, code in color_map.items():
        if fnmatch.fnmatch(basename, pattern):
            return code, tag_map.get(pattern)
    return None, None


def _load_global_defaults():
    """Load ~/.config/dendROS/defaults.yaml as baseline defaults."""
    path = os.path.expanduser('~/.config/dendROS/defaults.yaml')
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        keys = (
            'color_mode', 'show_group_tag', 'unmatched_color', 'debug', 'config_merge',
            'tag_position', 'colorize_launch_msgs', 'unmatched_tag', 'dim_unmatched',
            'crash_alert', 'crash_alert_color', 'crash_alert_interval',
            'traceback_color',
        )
        return {k: v for k, v in data.items() if k in keys}
    except Exception:
        return {}


def main():
    global _DEBUG
    global _crash_alert_enabled, _crash_alert_color, _crash_alert_interval
    global _traceback_color
    argv = sys.argv[1:]

    global_cfg = _load_global_defaults()
    if global_cfg.get('debug', False):
        _DEBUG = True

    _traceback_color      = global_cfg.get('traceback_color', 'fancy')
    _crash_alert_enabled  = bool(global_cfg.get('crash_alert', False))
    _crash_alert_color    = global_cfg.get('crash_alert_color', 'node')
    try:
        _crash_alert_interval = float(global_cfg.get('crash_alert_interval', 30))
    except (TypeError, ValueError):
        _crash_alert_interval = 30.0
    if _crash_alert_enabled:
        _write_pid_file()
        atexit.register(_cleanup)
        signal.signal(signal.SIGUSR1, _toggle_alert)

    pkg_name = extract_package_name(argv) if argv else None
    config_path = find_config(pkg_name) if pkg_name else None

    # Start with global defaults, then let per-package config override
    base = {
        'color_mode':           global_cfg.get('color_mode',           'tag_only'),
        'show_group_tag':       global_cfg.get('show_group_tag',       True),
        'unmatched_color':      global_cfg.get('unmatched_color',      None),
        'tag_position':         global_cfg.get('tag_position',         'after'),
        'colorize_launch_msgs': global_cfg.get('colorize_launch_msgs', True),
        'unmatched_tag':        global_cfg.get('unmatched_tag',        None),
        'dim_unmatched':        global_cfg.get('dim_unmatched',        False),
    }

    color_map, tag_map, mode_map, defaults = {}, {}, {}, base
    if config_path:
        try:
            color_map, tag_map, mode_map, pkg_defaults = load_config(config_path)
            defaults = {**base, **pkg_defaults}
        except Exception as e:
            print(f'\033[35;1m[dendROS]\033[0m config error ({config_path}): {e}',
                  file=sys.stderr, flush=True)

    config_merge = global_cfg.get('config_merge', True)
    if config_merge and argv and argv[0] == 'launch':
        launch_file_name = extract_launch_file(argv)
        launch_file_path = find_launch_file(pkg_name, launch_file_name) if launch_file_name else None
        if launch_file_path:
            included_pkgs = extract_included_packages(launch_file_path)
            for inc_pkg in included_pkgs:
                if inc_pkg == pkg_name:
                    continue
                inc_config_path = find_config(inc_pkg)
                if not inc_config_path:
                    continue
                try:
                    inc_color, inc_tag, inc_mode, _ = load_config(inc_config_path)
                    color_map, tag_map, mode_map = merge_color_maps(
                        color_map, tag_map, mode_map, [(inc_color, inc_tag, inc_mode)]
                    )
                    if _DEBUG:
                        _dbg(f'merged: {inc_pkg} ({inc_config_path})  +{len(inc_color)} node{"s" if len(inc_color) != 1 else ""}')
                except Exception as e:
                    print(f'\033[35;1m[dendROS]\033[0m config error ({inc_config_path}): {e}',
                          file=sys.stderr, flush=True)

    show_tag             = defaults.get('show_group_tag',       True)
    color_mode           = defaults.get('color_mode',           'tag_only')
    tag_position         = defaults.get('tag_position',         'after')
    colorize_launch_msgs = defaults.get('colorize_launch_msgs', True)
    unmatched_tag        = defaults.get('unmatched_tag') or None
    raw_unmatched        = defaults.get('unmatched_color') or None
    if not raw_unmatched and defaults.get('dim_unmatched', False):
        raw_unmatched = '2'   # ANSI dim — only when no explicit unmatched_color is set
    unmatched_color = _resolve_color(str(raw_unmatched)) if raw_unmatched else None

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

    def _colorize(line):
        """Apply full colorization pipeline to one line; return the colored line."""
        m = PREFIX_RE.match(line)
        if m and m.group(1) not in _LOG_LEVELS:
            node_name = m.group(1)
            code, label = resolve_node(node_name, color_map, tag_map)
            if code is None and unmatched_color:
                code, label = str(unmatched_color), unmatched_tag

            # Content after the "]" — strip exactly the separator space so that the
            # 2-space indentation of frame lines is preserved for traceback detection.
            rest = line[m.end():]
            content = rest[1:] if rest.startswith(' ') else rest

            if (_traceback_color != 'off' and
                    (_in_traceback or _TB_START_RE.match(content) or _TB_DURING_RE.match(content))):
                # Traceback block: dim node prefix + traceback content colors
                dim = _make_dim(code) if code else '2'
                tb_prefix = f'\033[{dim}m{m.group(0)}\033[0m '
                return _colorize_traceback(content, tb_prefix)

            if code:
                effective_mode = resolve_node_mode(node_name, mode_map) or color_mode
                return colorize_line(line, code, label, show_tag, effective_mode, tag_position)
            return line
        elif colorize_launch_msgs:
            lm = LAUNCH_RE.match(line)
            if lm:
                node_name = lm.group(3)
                code, _ = resolve_node(node_name, color_map, tag_map)
                if code is None and unmatched_color:
                    code = str(unmatched_color)
                if code:
                    return colorize_launch_msg(line, code, color_mode)
        return _colorize_traceback(line)

    try:
        for line in sys.stdin:
            new_death = False

            # Death detection on raw input before colorization
            if _crash_alert_enabled:
                dead_node, exit_code = _detect_death(line)
                if dead_node:
                    code, _ = resolve_node(dead_node, color_map, tag_map)
                    _dead_nodes.append((dead_node, exit_code, code))
                    new_death = True

            sys.stdout.write(_colorize(line))
            sys.stdout.flush()

            if _crash_alert_enabled:
                if new_death:
                    _print_alert_banner()
                elif (_dead_nodes and not _alert_dismissed
                      and _crash_alert_interval > 0
                      and time.monotonic() - _last_alert_time >= _crash_alert_interval):
                    _print_alert_banner()
    except KeyboardInterrupt:
        # Drain remaining input so ROS 2 shutdown messages / tracebacks reach the terminal
        try:
            for line in sys.stdin:
                sys.stdout.write(_colorize(line))
                sys.stdout.flush()
        except Exception:
            pass
    except BrokenPipeError:
        pass


if __name__ == '__main__':
    main()
