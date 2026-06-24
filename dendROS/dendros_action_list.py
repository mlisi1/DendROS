#!/usr/bin/env python3
"""Colorize ros2 action list output using dendROS node colors."""

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


def _node_path(action_name):
    """Extract the probable owning-node path: '/nav/navigate' → '/nav', '/action' → ''."""
    head, _ = action_name.rsplit('/', 1)
    return head


def _split_type(line):
    """Split 'name [type]' into (name, type_str) or (name, None) when no type present."""
    if line.endswith(']') and ' [' in line:
        name, rest = line.rsplit(' [', 1)
        return name, rest[:-1]
    return line, None


def _dim_type(type_str):
    """Render a type annotation as dim: ' [\033[2mtype\033[0m]'."""
    return f' [\033[2m{type_str}{RESET}]'


def main():
    cfg = load_global_config()
    show_tag      = cfg['show_group_tag']
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

    for line in sys.stdin:
        raw = line.rstrip('\n')
        if not raw:
            sys.stdout.write('\n')
            continue

        name, type_str = _split_type(raw)
        type_part = _dim_type(type_str) if type_str else ''

        node = _node_path(name)
        ansi_code, label = resolve_node(node, color_map, tag_map) if node else (None, None)

        if ansi_code:
            node_style = resolve_node_style(node, style_map) or tag_style
            colored    = f'\033[{ansi_code}m{name}{RESET}'
            if show_tag and label:
                badge = _badge(label, ansi_code, node_style)
                out = f'{badge} {colored}{type_part}'
            else:
                out = f'{colored}{type_part}'
        elif unmatched_ansi:
            colored = f'\033[{unmatched_ansi}m{name}{RESET}'
            if show_tag and unmatched_tag:
                badge = _badge(unmatched_tag, unmatched_ansi, tag_style)
                out = f'{badge} {colored}{type_part}'
            else:
                out = f'{colored}{type_part}'
        elif dim_unmatched:
            out = f'\033[2m{name}{RESET}{type_part}'
        else:
            out = f'{name}{type_part}'

        sys.stdout.write(out + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
