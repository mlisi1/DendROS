#!/usr/bin/env python3
"""Colorize and format ros2 param describe output using dendROS node colors."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yaml
except ImportError:
    yaml = None

from lib.config_loader import load_config, merge_color_maps, resolve_node, resolve_node_style
from lib.colors import RESET, _resolve_color
from lib.global_config import load_global_config, get_node_colors_path

_PARAM_NAME_RE = re.compile(r'^(Parameter name):\s+(.*)')


def _load_shared_colors():
    if yaml is None:
        return {}, {}, {}
    path = get_node_colors_path()
    if not os.path.isfile(path):
        return {}, {}, {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return (
            data.get('color_map', {}),
            data.get('tag_map', {}),
            data.get('style_map', {}),
        )
    except Exception:
        return {}, {}, {}


def _scan_configs():
    if yaml is None:
        return []
    seen, paths = set(), []
    for prefix in os.environ.get('AMENT_PREFIX_PATH', '').split(':'):
        share = os.path.join(prefix, 'share') if prefix else ''
        if not share or not os.path.isdir(share):
            continue
        try:
            for pkg in sorted(os.listdir(share)):
                candidate = os.path.join(share, pkg, 'config', 'dendROS.yaml')
                if os.path.isfile(candidate) and candidate not in seen:
                    seen.add(candidate)
                    paths.append(candidate)
        except OSError:
            pass
    return paths


def _badge(label, ansi_code, style):
    if style == 'inverted':
        return f'\033[{ansi_code};7m[{label}]{RESET}'
    return f'\033[{ansi_code}m[{label}]{RESET}'


def _parse_node_arg(argv):
    """Return the first positional argument that looks like a node path (starts with '/')."""
    for arg in argv:
        if arg.startswith('/'):
            return arg
    return None


def _format_key_value(indent, key, value):
    """Dim the key label; bold the section header when there is no value."""
    if value:
        return f'{indent}\033[2m{key}:\033[0m {value}'
    return f'{indent}\033[1m{key}:\033[0m'


def _colorize_line(raw, ansi_code, label, node_style,
                   unmatched_ansi, unmatched_tag, tag_style,
                   show_tag, dim_unmatched):
    """Return a formatted version of one output line."""
    if not raw.strip():
        return raw

    # ── Parameter name block header ──────────────────────────────────────────
    m = _PARAM_NAME_RE.match(raw)
    if m:
        param_name = m.group(2).strip()
        dim_label = f'\033[2mParameter name:\033[0m'

        if ansi_code:
            colored = f'\033[{ansi_code};1m{param_name}\033[0m'
            if show_tag and label:
                return f'{_badge(label, ansi_code, node_style)} {dim_label} {colored}'
            return f'{dim_label} {colored}'

        if unmatched_ansi:
            colored = f'\033[{unmatched_ansi};1m{param_name}\033[0m'
            if show_tag and unmatched_tag:
                return f'{_badge(unmatched_tag, unmatched_ansi, tag_style)} {dim_label} {colored}'
            return f'{dim_label} {colored}'

        if dim_unmatched:
            return f'{dim_label} \033[2m{param_name}\033[0m'

        return f'{dim_label} {param_name}'

    # ── Key: value lines (all indented fields) ────────────────────────────────
    stripped = raw.lstrip()
    indent = raw[:len(raw) - len(stripped)]

    if ':' in stripped:
        key, _, rest = stripped.partition(':')
        value = rest.lstrip()
        return _format_key_value(indent, key, value)

    return raw


def main():
    cfg = load_global_config()
    show_tag      = cfg['show_tag_cli']
    tag_style     = cfg['tag_style']
    unmatched_clr = cfg['unmatched_color']
    unmatched_tag = cfg['unmatched_tag']
    dim_unmatched = cfg['dim_unmatched']
    unmatched_ansi = _resolve_color(unmatched_clr) if unmatched_clr else None

    color_map, tag_map, style_map = _load_shared_colors()

    if not color_map:
        config_paths = _scan_configs()
        tuples = []
        for path in config_paths:
            try:
                c, t, m, s, k, _ = load_config(path)
                tuples.append((c, t, m, s, k))
            except Exception:
                pass
        if tuples:
            c0, t0, m0, s0, k0 = tuples[0]
            color_map, tag_map, _, style_map, _ = merge_color_maps(
                c0, t0, m0, s0, k0, tuples[1:]
            )

    node_arg = _parse_node_arg(sys.argv[1:])
    if node_arg:
        ansi_code, label = resolve_node(node_arg, color_map, tag_map)
        node_style = (resolve_node_style(node_arg, style_map) or tag_style) if ansi_code else tag_style
    else:
        ansi_code, label, node_style = None, None, tag_style

    for line in sys.stdin:
        raw = line.rstrip('\n')
        out = _colorize_line(
            raw, ansi_code, label, node_style,
            unmatched_ansi, unmatched_tag, tag_style,
            show_tag, dim_unmatched,
        )
        sys.stdout.write(out + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
