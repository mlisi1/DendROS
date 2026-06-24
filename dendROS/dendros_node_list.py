#!/usr/bin/env python3
"""Colorize ros2 node list output using all available dendROS.yaml configs."""

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
    """Read the color/tag/style maps written by the pipe on ros2 launch/run."""
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
    """Fallback: return paths to all dendROS.yaml files found in AMENT_PREFIX_PATH."""
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


def main():
    cfg = load_global_config()
    show_tag       = cfg['show_tag_cli']
    tag_position   = cfg['tag_position']
    tag_style      = cfg['tag_style']
    unmatched_clr  = cfg['unmatched_color']
    unmatched_tag  = cfg['unmatched_tag']
    dim_unmatched  = cfg['dim_unmatched']
    debug          = os.environ.get('DENDROS_DEBUG') == '1' or cfg.get('debug', False)
    unmatched_ansi = _resolve_color(unmatched_clr) if unmatched_clr else None

    # Primary source: shared file written by the pipe on ros2 launch/run
    color_map, tag_map, style_map = _load_shared_colors()

    if color_map:
        if debug:
            print(f'[dendROS node list] using shared node colors: {get_node_colors_path()}',
                  file=sys.stderr)
    else:
        # Fallback: scan AMENT_PREFIX_PATH for installed configs
        config_paths = _scan_configs()
        if debug:
            print(f'[dendROS node list] no shared colors found, scanning AMENT_PREFIX_PATH',
                  file=sys.stderr)
            print(f'[dendROS node list] AMENT_PREFIX_PATH={os.environ.get("AMENT_PREFIX_PATH", "<not set>")}',
                  file=sys.stderr)
            print(f'[dendROS node list] configs found: {config_paths or "<none>"}', file=sys.stderr)

        tuples = []
        for path in config_paths:
            try:
                c, t, m, s, k, _ = load_config(path)
                tuples.append((c, t, m, s, k))
            except Exception as e:
                if debug:
                    print(f'[dendROS node list] error loading {path}: {e}', file=sys.stderr)

        if tuples:
            c0, t0, m0, s0, k0 = tuples[0]
            color_map, tag_map, _, style_map, _ = merge_color_maps(
                c0, t0, m0, s0, k0, tuples[1:]
            )

    if debug:
        print(f'[dendROS node list] color_map keys: {list(color_map.keys()) or "<empty>"}',
              file=sys.stderr)

    if not color_map and debug:
        print('[dendROS node list] no colors loaded — passthrough mode', file=sys.stderr)

    for line in sys.stdin:
        node = line.rstrip('\n')
        if not node:
            sys.stdout.write('\n')
            continue

        ansi_code, label = resolve_node(node, color_map, tag_map)

        if ansi_code:
            node_style = resolve_node_style(node, style_map) or tag_style
            colored    = f'\033[{ansi_code}m{node}{RESET}'
            if show_tag and label:
                badge = _badge(label, ansi_code, node_style)
                out = f'{badge} {colored}' if tag_position == 'before' else f'{colored} {badge}'
            else:
                out = colored
        elif unmatched_ansi:
            colored = f'\033[{unmatched_ansi}m{node}{RESET}'
            if show_tag and unmatched_tag:
                badge = _badge(unmatched_tag, unmatched_ansi, tag_style)
                out = f'{badge} {colored}' if tag_position == 'before' else f'{colored} {badge}'
            else:
                out = colored
        elif dim_unmatched:
            out = f'\033[2m{node}{RESET}'
        else:
            out = node

        sys.stdout.write(out + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
