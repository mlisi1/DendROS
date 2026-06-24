"""Background watcher for /parameter_events — queues param change notifications.

Architecture
------------
A single daemon thread runs `ros2 topic echo /parameter_events` as a subprocess
and parses its YAML output (message chunks separated by `---` lines).  Each
chunk that represents a genuine runtime change (changed_parameters non-empty,
not a CLI daemon node) is pushed to `_queue`.

The main pipe thread calls `drain()` between stdin lines to pop all pending
events and get back formatted notification strings.  No locking is needed
because only the daemon thread writes to _queue and only the main thread reads
from it (queue.Queue is already thread-safe).
"""

import atexit
import os
import queue
import shutil
import subprocess
import threading

try:
    import yaml
except ImportError:
    yaml = None

_RESET = '\033[0m'
# White-bg + black-text strip used in the inverted alert style
_WB = '\033[107;30m'

# [dendROS] header matches the logo title: "[dend" in logo-blue, "ROS]" in logo-orange
_DENDROS = '\033[38;2;0;75;107;1m[dend\033[38;2;224;127;0;1mROS]\033[0m'

# Inverted-style header: logo colors as BACKGROUNDS, black text (hollow/cutout letters).
# \033[30m sets black fg once; subsequent bg changes leave fg unchanged.
_DENDROS_INV = (
    '\033[48;2;0;75;107;1m\033[30m[dend'  # logo-blue bg + bold + black text
    '\033[48;2;224;127;0;1mROS]'           # logo-orange bg + bold (fg stays black)
    '\033[0m\033[107;30m'                  # reset → white bg + black text for rest
)


def _fg_to_bg(code: str) -> str:
    """Convert a foreground ANSI SGR code string to its background equivalent.

    Standard 30-37 → 40-47, bright 90-97 → 100-107, 24-bit 38;2;R;G;B → 48;2;R;G;B.
    Bold and other modifiers are dropped so the caller can add its own text attributes.
    """
    parts = code.split(';')
    out = []
    i = 0
    while i < len(parts):
        p = parts[i]
        n = int(p) if p.isdigit() else -1
        if 30 <= n <= 37:
            out.append(str(n + 10)); i += 1
        elif 90 <= n <= 97:
            out.append(str(n + 10)); i += 1
        elif n == 38 and i + 1 < len(parts):
            if parts[i + 1] == '2' and i + 4 < len(parts):
                out += ['48', '2'] + parts[i + 2:i + 5]; i += 5
            elif parts[i + 1] == '5' and i + 2 < len(parts):
                out += ['48', '5', parts[i + 2]]; i += 3
            else:
                i += 1
        else:
            i += 1  # drop bold and other non-color modifiers
    return ';'.join(out) if out else '0'

_queue = queue.Queue()
_proc: 'subprocess.Popen | None' = None
_param_cache: dict = {}  # (node, param_name) → last-seen value string

# ParameterType enum → value field name in the YAML message
_TYPE_FIELDS = {
    1: 'bool_value',
    2: 'integer_value',
    3: 'double_value',
    4: 'string_value',
    5: 'byte_array_value',
    6: 'bool_array_value',
    7: 'integer_array_value',
    8: 'double_array_value',
    9: 'string_array_value',
}
_MAX_VALUE_LEN = 60


def _find_ros2():
    b = shutil.which('ros2')
    if b:
        return b
    distro = os.environ.get('ROS_DISTRO', '')
    if distro:
        c = f'/opt/ros/{distro}/bin/ros2'
        if os.path.isfile(c):
            return c
    return None


def _extract_value(v):
    """Return a human-readable string for a ParameterValue dict."""
    if not isinstance(v, dict):
        return str(v) if v is not None else ''
    field = _TYPE_FIELDS.get(v.get('type', 0))
    if not field:
        return ''
    val = v.get(field, '')
    if isinstance(val, bool):
        return 'true' if val else 'false'
    if isinstance(val, list):
        s = str(val)
        return (s[:_MAX_VALUE_LEN] + '…') if len(s) > _MAX_VALUE_LEN else s
    return str(val)


def _process_chunk(lines, color_map, tag_map, scope, resolve_node_fn):
    """Parse one YAML message chunk; enqueue any changed-parameter events."""
    try:
        msg = yaml.safe_load('\n'.join(lines))
    except Exception:
        return
    if not isinstance(msg, dict):
        return

    node = msg.get('node', '')
    # /_ros2cli_XXXXX nodes are transient CLI tool nodes — always skip
    if not node or node.startswith('/_ros2cli_'):
        return

    changed = msg.get('changed_parameters') or []
    if not changed:
        return

    if scope == 'tracked':
        code, _ = resolve_node_fn(node, color_map, tag_map)
        if not code:
            return

    for param in changed:
        if not isinstance(param, dict):
            continue
        name = param.get('name', '')
        if not name:
            continue
        new_val = _extract_value(param.get('value', {}))
        cache_key = (node, name)
        old_val = _param_cache.get(cache_key)  # None on first ever change
        _param_cache[cache_key] = new_val
        _queue.put((node, name, old_val, new_val))


def _watch(color_map, tag_map, scope):
    """Background thread: stream /parameter_events and fill the queue."""
    global _proc
    ros2 = _find_ros2()
    if not ros2:
        return

    try:
        _proc = subprocess.Popen(
            [ros2, 'topic', 'echo', '/parameter_events'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return

    from lib.config_loader import resolve_node  # deferred — avoids import cycles

    chunk: list[str] = []
    try:
        for raw in _proc.stdout:
            line = raw.rstrip('\n')
            if line == '---':
                if chunk:
                    _process_chunk(chunk, color_map, tag_map, scope, resolve_node)
                chunk = []
            else:
                chunk.append(line)
    except Exception:
        pass


@atexit.register
def _cleanup():
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.terminate()
        except Exception:
            pass


def setup(color_map, tag_map, scope: str):
    """Start the background watcher.  No-op when yaml or ros2 binary is unavailable."""
    if yaml is None or not _find_ros2():
        return
    t = threading.Thread(target=_watch, args=(color_map, tag_map, scope), daemon=True)
    t.start()


def _fmt_inline(node, name, old_val, value, code, label, node_style, show_tag):
    """Rainbow header + plain 'param' + node color identity + bold param data."""
    old_part = f'{old_val} → ' if old_val is not None else '? → '
    if code:
        node_str = f'\033[{code}m{node}{_RESET}'
        if show_tag and label:
            badge = (f'\033[{code};7m[{label}]{_RESET}'
                     if node_style == 'inverted'
                     else f'\033[{code}m[{label}]{_RESET}')
            node_str = f'{badge} {node_str}'
    else:
        node_str = node  # untracked in "all" mode

    return (
        f'{_DENDROS} param'
        f'  {node_str}  \033[1m{name}\033[0m: {old_part}{value}\n'
    )


def _fmt_inverted(node, name, old_val, value, code, label, node_style, show_tag):
    """[dendROS] header + continuous white-bg strip from 'param' to EOL.

    Layout:
      [blue/orange][dend|ROS][reset][WB] param  [node-bg;black][TAG] /node[WB]  [bold]name[/bold]: old→new [K][reset]

    The white-bg (_WB) starts immediately after [dendROS] and is never interrupted
    by a bare reset — the node-identity island switches to its explicit bg and then
    returns to _WB, so every space in the line (including between sections) is white.
    \033[K fills the remainder of the console line with the white bg.
    """
    old_part = f'{old_val} → ' if old_val is not None else '? → '

    if code:
        node_bg = _fg_to_bg(code)
        if show_tag and label:
            node_section = f'\033[{node_bg};30m[{label}] {node}{_WB}'
        else:
            node_section = f'\033[{node_bg};30m{node}{_WB}'
    else:
        node_section = node  # untracked — plain black text on the white bg

    return (
        f'{_DENDROS_INV} param  {node_section}'
        f'  \033[1m{name}\033[22m: {old_part}{value} \033[K{_RESET}\n'
    )


def drain(color_map, tag_map, style_map, tag_style: str, show_tag: bool,
          alert_style: str = 'inline') -> list[str]:
    """Pop all pending change events; return formatted notification lines (with \\n).

    Must be called from the main thread only.
    """
    from lib.config_loader import resolve_node, resolve_node_style

    lines: list[str] = []
    while True:
        try:
            node, name, old_val, value = _queue.get_nowait()
        except queue.Empty:
            break

        code, label = resolve_node(node, color_map, tag_map)
        node_style = (resolve_node_style(node, style_map) or tag_style) if code else tag_style

        if alert_style == 'inverted':
            lines.append(_fmt_inverted(node, name, old_val, value, code, label, node_style, show_tag))
        else:
            lines.append(_fmt_inline(node, name, old_val, value, code, label, node_style, show_tag))

    return lines
