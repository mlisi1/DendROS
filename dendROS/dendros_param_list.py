#!/usr/bin/env python3
"""Colorize ros2 param list output using dendROS node colors."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import yaml
except ImportError:
    yaml = None

from lib.config_loader import load_config, merge_color_maps, resolve_node, resolve_node_style
from lib.colors import RESET, _resolve_color
from lib.global_config import load_global_config, get_node_colors_path


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


def _split_param_type(param):
    """Split 'name (type)' → (name, type_str) or (name, None)."""
    if param.endswith(')') and ' (' in param:
        name, rest = param.rsplit(' (', 1)
        return name, rest[:-1]
    return param, None


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

    current_ansi = None   # color code of the most recent node header
    current_style = None  # tag_style of the most recent node header

    # Pre-seed color from the node argument so bare output (no header line) is colored.
    # When a node header IS in the output the header parser will simply overwrite this.
    node_arg = _parse_node_arg(sys.argv[1:])
    if node_arg:
        _ansi, _label = resolve_node(node_arg, color_map, tag_map)
        if _ansi:
            current_ansi = _ansi
            current_style = resolve_node_style(node_arg, style_map) or tag_style
        elif unmatched_ansi:
            current_ansi = unmatched_ansi
            current_style = tag_style

    for line in sys.stdin:
        raw = line.rstrip('\n')
        stripped = raw.lstrip()

        if not raw:
            sys.stdout.write('\n')
            continue

        indent = raw[: len(raw) - len(stripped)]

        # Node header: '/node_name:' — no leading whitespace, ends with ':'
        if not indent and stripped.endswith(':'):
            node_name = stripped[:-1]  # drop the trailing ':'
            ansi_code, label = resolve_node(node_name, color_map, tag_map)

            if ansi_code:
                current_ansi = ansi_code
                node_style = resolve_node_style(node_name, style_map) or tag_style
                current_style = node_style
                colored_name = f'\033[{ansi_code}m{node_name}:{RESET}'
                if show_tag and label:
                    badge = _badge(label, ansi_code, node_style)
                    out = f'{badge} {colored_name}'
                else:
                    out = colored_name
            elif unmatched_ansi:
                current_ansi = unmatched_ansi
                current_style = tag_style
                colored_name = f'\033[{unmatched_ansi}m{node_name}:{RESET}'
                if show_tag and unmatched_tag:
                    badge = _badge(unmatched_tag, unmatched_ansi, tag_style)
                    out = f'{badge} {colored_name}'
                else:
                    out = colored_name
            elif dim_unmatched:
                current_ansi = None
                current_style = None
                out = f'\033[2m{node_name}:{RESET}'
            else:
                current_ansi = None
                current_style = None
                out = raw

            sys.stdout.write(out + '\n')
            sys.stdout.flush()
            continue

        # Param line: indented under a node header
        param_name, type_str = _split_param_type(stripped)
        type_part = f' (\033[2m{type_str}{RESET})' if type_str else ''

        if current_ansi:
            out = f'{indent}\033[{current_ansi}m\033[2m{param_name}{RESET}{type_part}'
        elif dim_unmatched:
            out = f'{indent}\033[2m{param_name}{RESET}{type_part}'
        else:
            out = f'{indent}{param_name}{type_part}'

        sys.stdout.write(out + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
