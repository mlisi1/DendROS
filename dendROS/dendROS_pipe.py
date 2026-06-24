#!/usr/bin/env python3
"""DendROS colorizer pipe — reads ros2 output from stdin and colorizes by node group."""

import os
import re
import sys
import time

try:
    import termios as _termios
    _OPOST = getattr(_termios, 'OPOST', 1)
except ImportError:
    _termios = None
    _OPOST = 1

try:
    import yaml
except ImportError:
    for line in sys.stdin:
        sys.stdout.write(line)
        sys.stdout.flush()
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.colors import make_dim
from lib.colorizers import PREFIX_RE, LAUNCH_RE, _LOG_LEVELS, colorize_line, colorize_launch_msg
from lib.config_loader import load_config, merge_color_maps, resolve_node, resolve_node_mode, resolve_node_style
from lib.keywords import build_keyword_highlights, resolve_node_keywords, apply_keyword_highlights
from lib.discovery import (
    extract_package_name, extract_launch_file, find_config,
    find_launch_file, extract_included_packages,
)
from lib.global_config import load_global_config, get_node_colors_path
import lib.crash_alert as ca
import lib.traceback_color as tc
import lib.param_watcher as pw

_DEBUG = os.environ.get('DENDROS_DEBUG', '') not in ('', '0')

# Extracts the logger name from a ROS 2 log line tail (after the process prefix).
# Format after prefix: " [LEVEL] [timestamp] [logger_name]: message"
# The logger name is the ROS node name as registered in the graph (what ros2 node list shows).
_ANSI_RE   = re.compile(r'\033\[[0-9;]*m')
_LOGGER_RE = re.compile(
    r'^\s*(?:\033\[[0-9;]*m)*'
    r'\[(?:INFO|WARN(?:ING)?|ERROR|DEBUG|FATAL)\]'
    r'(?:\033\[[0-9;]*m)*'
    r'\s*\[\d[^\]]*\]'      # timestamp bracket
    r'\s*\[([^\]]+)\]\s*:'  # [logger_name]:
)


def _dbg(msg):
    print(f'\033[35;1m[dendROS]\033[0m {msg}', file=sys.stderr, flush=True)


def _save_node_colors(color_map, tag_map, style_map):
    """Write color/tag/style maps to the shared node_colors file for cross-terminal use.

    Always overwrites the file with the current in-memory maps so stale entries
    from a previous launch's config never survive into the current run.
    """
    import tempfile
    path = get_node_colors_path()
    cfg_dir = os.path.dirname(path)

    data = {
        'color_map': dict(color_map),
        'tag_map':   dict(tag_map),
        'style_map': dict(style_map),
    }

    try:
        os.makedirs(cfg_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cfg_dir, suffix='.tmp')
        with os.fdopen(fd, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
        os.replace(tmp, path)
    except Exception:
        pass


def main():
    global _DEBUG
    argv = sys.argv[1:]

    global_cfg = load_global_config()
    if global_cfg.get('debug', False):
        _DEBUG = True

    tc.set_mode(global_cfg.get('traceback_color', 'fancy'))

    try:
        interval = float(global_cfg.get('crash_alert_interval', 30))
    except (TypeError, ValueError):
        interval = 30.0
    ca.setup(
        enabled=bool(global_cfg.get('crash_alert', False)),
        color=global_cfg.get('crash_alert_color', 'node'),
        interval=interval,
    )

    pkg_name    = extract_package_name(argv) if argv else None
    config_path = find_config(pkg_name) if pkg_name else None

    base = {
        'color_mode':           global_cfg.get('color_mode',           'tag_only'),
        'show_group_tag':       global_cfg.get('show_tag_launch',      True),
        'unmatched_color':      global_cfg.get('unmatched_color',      None),
        'tag_position':         global_cfg.get('tag_position',         'after'),
        'colorize_launch_msgs': global_cfg.get('colorize_launch_msgs', True),
        'unmatched_tag':        global_cfg.get('unmatched_tag',        None),
        'dim_unmatched':        global_cfg.get('dim_unmatched',        False),
        'tag_style':            global_cfg.get('tag_style',            'normal'),
    }

    color_map, tag_map, mode_map, style_map, keyword_map, defaults = {}, {}, {}, {}, {}, base
    if config_path:
        try:
            color_map, tag_map, mode_map, style_map, keyword_map, pkg_defaults = load_config(config_path)
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
                    inc_color, inc_tag, inc_mode, inc_style, inc_kw, _ = load_config(inc_config_path)
                    color_map, tag_map, mode_map, style_map, keyword_map = merge_color_maps(
                        color_map, tag_map, mode_map, style_map, keyword_map,
                        [(inc_color, inc_tag, inc_mode, inc_style, inc_kw)]
                    )
                    if _DEBUG:
                        _dbg(f'merged: {inc_pkg} ({inc_config_path})  +{len(inc_color)} node{"s" if len(inc_color) != 1 else ""}')
                except Exception as e:
                    print(f'\033[35;1m[dendROS]\033[0m config error ({inc_config_path}): {e}',
                          file=sys.stderr, flush=True)

    if config_path:
        _save_node_colors(color_map, tag_map, style_map)

    param_alert         = bool(global_cfg.get('param_change_alert', False))
    param_alert_scope   = global_cfg.get('param_change_alert_scope', 'tracked')
    param_alert_style   = global_cfg.get('param_change_alert_style', 'inline')
    if param_alert:
        pw.setup(color_map, tag_map, param_alert_scope)

    show_tag             = defaults.get('show_group_tag',       True)
    color_mode           = defaults.get('color_mode',           'tag_only')
    tag_position         = defaults.get('tag_position',         'after')
    tag_style            = defaults.get('tag_style',            'normal')
    colorize_launch_msgs = defaults.get('colorize_launch_msgs', True)
    unmatched_tag        = defaults.get('unmatched_tag') or None
    raw_unmatched        = defaults.get('unmatched_color') or None
    if not raw_unmatched and defaults.get('dim_unmatched', False):
        raw_unmatched = '2'
    from lib.colors import _resolve_color
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

    # teleop_twist_keyboard and similar nodes call tty.setraw() on the shared
    # terminal, which disables OPOST/ONLCR output processing.  In raw mode \n
    # only moves the cursor down (not back to col 0), so each help-text line
    # appears indented by the length of the previous one.
    #
    # Fix: check the ACTUAL terminal mode at emit-time (the mode toggles on
    # every keypress: setraw → read key → tcsetattr restore).  Only add \r
    # when raw mode is active; in cooked mode ONLCR already does this.
    # Never adding \r unconditionally avoids the double-\r (\r\r\n) that
    # cooked-mode terminals produce, which visually erases multi-line output
    # (e.g. tracebacks) by moving the cursor to col 0 mid-line.
    _stdout_tty = sys.stdout.isatty()
    _stdout_fd  = sys.stdout.fileno() if _stdout_tty else -1

    def _emit(text):
        if _stdout_tty and _termios is not None:
            try:
                if not (_termios.tcgetattr(_stdout_fd)[1] & _OPOST):
                    text = text.replace('\r\n', '\n').replace('\n', '\r\n')
            except Exception:
                pass
        sys.stdout.write(text)
        sys.stdout.flush()

    def _colorize(line):
        """Apply full colorization pipeline to one line; return the colored line."""
        m = PREFIX_RE.match(line)
        if m and m.group(1) not in _LOG_LEVELS:
            node_name = m.group(1)
            code, label = resolve_node(node_name, color_map, tag_map)

            rest = line[m.end():]
            content = rest[1:] if rest.startswith(' ') else rest

            # Bidirectional logger-name discovery.
            # ROS 2 format: "[LEVEL] [timestamp] [logger_name]: msg"
            # logger_name is the ROS node name registered in the graph (what
            # ros2 node list shows). It can differ from node_name (the launch
            # process name) when a node hard-codes its own name in C++ — e.g.
            # slam_toolbox launched as slam_node still logs as slam_toolbox.
            lm = _LOGGER_RE.match(rest)
            logger_name = lm.group(1) if lm else None

            if code is not None:
                # Forward: process name in config → add ROS node name to map.
                # Also propagate tag when the logger is already coloured (e.g. from
                # a previous launch) but lacks a tag because it was discovered before
                # the config had labels.
                if logger_name and logger_name != node_name:
                    if logger_name not in color_map:
                        color_map[logger_name] = code
                        if node_name in tag_map:
                            tag_map[logger_name] = tag_map[node_name]
                        if node_name in style_map:
                            style_map[logger_name] = style_map[node_name]
                        _save_node_colors(color_map, tag_map, style_map)
                    elif not tag_map.get(logger_name) and tag_map.get(node_name):
                        tag_map[logger_name] = tag_map[node_name]
                        _save_node_colors(color_map, tag_map, style_map)
            elif logger_name:
                # Reverse: ROS node name in config → use its color for the process name
                logger_code, logger_label = resolve_node(logger_name, color_map, tag_map)
                if logger_code is not None:
                    code, label = logger_code, logger_label
                    if node_name not in color_map:
                        color_map[node_name] = logger_code
                        if logger_name in tag_map:
                            tag_map[node_name] = tag_map[logger_name]
                        if logger_name in style_map:
                            style_map[node_name] = style_map[logger_name]
                        _save_node_colors(color_map, tag_map, style_map)
                    elif not tag_map.get(node_name) and logger_label:
                        tag_map[node_name] = logger_label
                        _save_node_colors(color_map, tag_map, style_map)

            if code is None and unmatched_color:
                code, label = str(unmatched_color), unmatched_tag

            if (tc._traceback_color != 'off' and
                    (tc._in_traceback or tc._TB_START_RE.match(content) or tc._TB_DURING_RE.match(content))):
                ca.mark_traceback(node_name)
                dim = make_dim(code) if code else '2'
                tb_prefix = f'\033[{dim}m{m.group(0)}\033[0m '
                return tc.colorize_traceback(content, tb_prefix)

            if code:
                effective_mode  = resolve_node_mode(node_name, mode_map) or color_mode
                effective_style = resolve_node_style(node_name, style_map) or tag_style
                colored = colorize_line(line, code, label, show_tag, effective_mode, tag_position, effective_style)
                node_kws = resolve_node_keywords(node_name, keyword_map)
                pkg_kws  = build_keyword_highlights(defaults.get('highlight') or defaults.get('highlights') or [], code)
                all_kws  = node_kws + pkg_kws
                return apply_keyword_highlights(colored, all_kws) if all_kws else colored
            return line
        elif colorize_launch_msgs:
            # RCUTILS_COLORIZED_OUTPUT=1 (set by dendROS.sh) causes rcutils to embed
            # ANSI codes in the level bracket even when output is piped.  Strip them
            # before matching so LAUNCH_RE (which expects a literal '[INFO]') works.
            bare = _ANSI_RE.sub('', line) if '\033' in line else line
            lm = LAUNCH_RE.match(bare)
            if lm:
                node_name = lm.group(3)
                code, _ = resolve_node(node_name, color_map, tag_map)
                if code is None and unmatched_color:
                    code = str(unmatched_color)
                if code:
                    launch_colored = colorize_launch_msg(bare, code, color_mode)
                    node_kws = resolve_node_keywords(node_name, keyword_map)
                    pkg_kws  = build_keyword_highlights(defaults.get('highlight') or defaults.get('highlights') or [], code)
                    all_kws  = node_kws + pkg_kws
                    return apply_keyword_highlights(launch_colored, all_kws) if all_kws else launch_colored
        return tc.colorize_traceback(line)

    def _iter_stdin():
        """Yield lines from stdin, treating \\r, \\n, and \\r\\n as line terminators.

        Using the raw binary stream bypasses Python's internal readline buffer so
        \\r-terminated updates (e.g. teleop_twist_keyboard speed display) are
        yielded and passed through immediately, not held until the next \\n.

        When Ctrl+C is pressed, SIGINT interrupts the blocking read() syscall and
        Python raises KeyboardInterrupt *inside the generator*.  A generator that
        propagates an unhandled exception is permanently exhausted — the caller's
        except-KeyboardInterrupt handler then has nothing left to drain.  Fix: catch
        the first interrupt and continue so node-shutdown tracebacks still appear.
        A second interrupt (or any I/O error) ends the generator immediately.
        """
        buf = b''
        raw = sys.stdin.buffer.raw
        _sigint_seen = False
        while True:
            try:
                data = raw.read(4096)
            except KeyboardInterrupt:
                if _sigint_seen:
                    if buf:
                        yield buf.decode('utf-8', errors='replace')
                    return
                _sigint_seen = True
                ca.enter_shutdown_mode()  # cascade deaths after Ctrl+C are expected
                continue  # drain shutdown tracebacks on first Ctrl+C
            except (OSError, IOError):
                break
            if not data:
                if buf:
                    yield buf.decode('utf-8', errors='replace')
                break
            buf += data
            while True:
                r = buf.find(b'\r')
                n = buf.find(b'\n')
                if n < 0 and r < 0:
                    break
                if n >= 0 and (r < 0 or n < r):
                    yield buf[:n+1].decode('utf-8', errors='replace')
                    buf = buf[n+1:]
                else:
                    end = r + 1
                    if end < len(buf) and buf[end] == 10:  # \r\n → single terminator
                        end += 1
                    yield buf[:end].decode('utf-8', errors='replace')
                    buf = buf[end:]

    stdin_lines = _iter_stdin()

    try:
        for line in stdin_lines:
            new_death = False

            if ca._crash_alert_enabled:
                dead_node, exit_code = ca.detect_death(line)
                if dead_node:
                    code, _ = resolve_node(dead_node, color_map, tag_map)
                    ca.record_death(dead_node, exit_code, code)
                    new_death = True
                else:
                    restarted = ca.detect_restart(line)
                    if restarted:
                        ca.handle_restart(restarted)

            _emit(_colorize(line))

            if param_alert:
                for notif in pw.drain(color_map, tag_map, style_map, tag_style, show_tag,
                                      param_alert_style):
                    _emit(notif)

            if ca._crash_alert_enabled:
                if new_death:
                    ca.print_alert_banner()
                elif (ca._dead_nodes
                      and ca._crash_alert_interval > 0
                      and time.monotonic() - ca._last_alert_time >= ca._crash_alert_interval):
                    ca.print_alert_banner()
    except KeyboardInterrupt:
        try:
            for line in stdin_lines:  # same generator — continues from where interrupted
                _emit(_colorize(line))
        except Exception:
            pass
    except BrokenPipeError:
        pass


if __name__ == '__main__':
    main()
