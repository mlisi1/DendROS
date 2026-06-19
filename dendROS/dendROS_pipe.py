#!/usr/bin/env python3
"""DendROS colorizer pipe — reads ros2 output from stdin and colorizes by node group."""

import os
import sys
import time

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
from lib.global_config import load_global_config
import lib.crash_alert as ca
import lib.traceback_color as tc

_DEBUG = os.environ.get('DENDROS_DEBUG', '') not in ('', '0')


def _dbg(msg):
    print(f'\033[35;1m[dendROS]\033[0m {msg}', file=sys.stderr, flush=True)


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
        'show_group_tag':       global_cfg.get('show_group_tag',       True),
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

    def _colorize(line):
        """Apply full colorization pipeline to one line; return the colored line."""
        m = PREFIX_RE.match(line)
        if m and m.group(1) not in _LOG_LEVELS:
            node_name = m.group(1)
            code, label = resolve_node(node_name, color_map, tag_map)
            if code is None and unmatched_color:
                code, label = str(unmatched_color), unmatched_tag

            rest = line[m.end():]
            content = rest[1:] if rest.startswith(' ') else rest

            if (tc._traceback_color != 'off' and
                    (tc._in_traceback or tc._TB_START_RE.match(content) or tc._TB_DURING_RE.match(content))):
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
            lm = LAUNCH_RE.match(line)
            if lm:
                node_name = lm.group(3)
                code, _ = resolve_node(node_name, color_map, tag_map)
                if code is None and unmatched_color:
                    code = str(unmatched_color)
                if code:
                    launch_colored = colorize_launch_msg(line, code, color_mode)
                    node_kws = resolve_node_keywords(node_name, keyword_map)
                    pkg_kws  = build_keyword_highlights(defaults.get('highlight') or defaults.get('highlights') or [], code)
                    all_kws  = node_kws + pkg_kws
                    return apply_keyword_highlights(launch_colored, all_kws) if all_kws else launch_colored
        return tc.colorize_traceback(line)

    try:
        for line in sys.stdin:
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

            sys.stdout.write(_colorize(line))
            sys.stdout.flush()

            if ca._crash_alert_enabled:
                if new_death:
                    ca.print_alert_banner()
                elif (ca._dead_nodes
                      and ca._crash_alert_interval > 0
                      and time.monotonic() - ca._last_alert_time >= ca._crash_alert_interval):
                    ca.print_alert_banner()
    except KeyboardInterrupt:
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
