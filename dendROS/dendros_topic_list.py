#!/usr/bin/env python3
"""Colorize ros2 topic list with publisher color and aligned pub/sub count indicators."""

import json
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
import lib.ros_graph as ros_graph

_INDENT = '  '

# System topics shown plain (no color, tag, or count blocks)
_SYSTEM_TOPICS = {'/parameter_events', '/rosout'}


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


def _nodes_to_groups(nodes, color_map, tag_map):
    """[(code, count), ...] ordered by first encounter."""
    counts = {}
    order  = []
    for node in nodes:
        code, _ = resolve_node(node, color_map, tag_map)
        if code:
            if code not in counts:
                order.append(code)
            counts[code] = counts.get(code, 0) + 1
    return [(c, counts[c]) for c in order]


def _count_blocks(groups):
    return ' '.join(f'\033[{c};7m{n}\033[0m' for c, n in groups)


def _vis_pub_w(groups):
    """Visual (plain-text) width of pub count blocks."""
    if not groups:
        return 0
    return sum(len(str(n)) for _, n in groups) + max(0, len(groups) - 1)


def _vis_mid_w(badge_label, name, type_str):
    """Visual width of the middle column: '[LABEL] name [type]'.
    Pass badge_label=None when no badge is shown."""
    w = len(name)
    if type_str:
        w += len(type_str) + 3   # ' [' + type + ']'
    if badge_label:
        w += len(badge_label) + 3 + 1  # '[LBL] '
    return w


def _split_type(line):
    if line.endswith(']') and ' [' in line:
        name, rest = line.rsplit(' [', 1)
        return name, rest[:-1]
    return line, None


def _sort_by_group(render_info):
    """Reorder render_info for topic_sort='group':
    system topics first (original order), then matched topics grouped by color
    (groups in first-occurrence order, alphabetical within group), then
    unmatched/dim/plain topics alphabetically. Empty lines are dropped."""
    system  = [x for x in render_info if x[0] == 'system']
    matched = [x for x in render_info if x[0] == 'matched']
    other   = [x for x in render_info if x[0] not in ('empty', 'system', 'matched')]

    group_order = {}
    for item in matched:
        ansi = item[1]
        if ansi not in group_order:
            group_order[ansi] = len(group_order)

    matched_sorted = sorted(matched, key=lambda x: (group_order.get(x[1], 999), x[6]))
    other_sorted   = sorted(other,   key=lambda x: x[6] or '')

    return system + matched_sorted + other_sorted


def _fetch_from_env(item_set, env_key):
    ov = os.environ.get(env_key)
    if ov is None:
        return None
    try:
        injected = json.loads(ov)
    except (json.JSONDecodeError, ValueError):
        injected = {}
    return {item: injected.get(item, []) for item in item_set}


def main():
    cfg = load_global_config()
    show_tag       = cfg['show_tag_cli']
    tag_style      = cfg['tag_style']
    unmatched_clr  = cfg['unmatched_color']
    unmatched_tag  = cfg['unmatched_tag']
    dim_unmatched  = cfg['dim_unmatched']
    topic_sort     = cfg.get('topic_sort', 'default')
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

    # ── Parse input ───────────────────────────────────────────────────────────
    raw_lines  = [line.rstrip('\n') for line in sys.stdin]
    all_topics = set()   # excludes system topics
    parsed     = []      # [(raw, name_or_None, type_str_or_None)]

    for raw in raw_lines:
        if not raw:
            parsed.append((raw, None, None))
            continue
        name, type_str = _split_type(raw)
        if name not in _SYSTEM_TOPICS:
            all_topics.add(name)
        parsed.append((raw, name, type_str))

    # ── Graph query (system topics excluded) ──────────────────────────────────
    pub_ov = _fetch_from_env(all_topics, 'DENDROS_TOPIC_PUBLISHERS')
    sub_ov = _fetch_from_env(all_topics, 'DENDROS_TOPIC_SUBSCRIBERS')
    pub_nodes = pub_ov or {}
    sub_nodes = sub_ov or {}

    if color_map and all_topics and (pub_ov is None or sub_ov is None):
        live_pub = all_topics if pub_ov is None else set()
        live_sub = all_topics if sub_ov is None else set()
        try:
            graph = ros_graph.get_all_providers(topics=live_pub, pub_topics=live_sub)
            if pub_ov is None:
                pub_nodes = {t: graph.get(t, []) for t in live_pub}
            if sub_ov is None:
                sub_nodes = {t: graph.get(ros_graph._PUB_SUB_PREFIX + t, [])
                             for t in live_sub}
        except Exception:
            pass

    pub_groups = {t: _nodes_to_groups(pub_nodes.get(t, []), color_map, tag_map)
                  for t in all_topics}
    sub_groups = {t: _nodes_to_groups(sub_nodes.get(t, []), color_map, tag_map)
                  for t in all_topics}

    # ── Pass 1: resolve rendering case + visual widths ────────────────────────
    # Tuple: (case, ansi, badge_label, node_style, pgroups, sgroups, name, type_str)
    render_info = []
    pub_vws     = []   # per non-system topic
    mid_vws     = []   # per non-system topic

    for raw, name, type_str in parsed:
        if not name:
            render_info.append(('empty', None, None, None, [], [], None, None))
            continue

        if name in _SYSTEM_TOPICS:
            render_info.append(('system', None, None, None, [], [], name, type_str))
            continue

        pgroups  = pub_groups.get(name, [])
        sgroups  = sub_groups.get(name, [])
        pub_list = pub_nodes.get(name, [])
        primary  = pub_list[0] if pub_list else None

        if primary:
            ansi, badge_label = resolve_node(primary, color_map, tag_map)
            ns                = resolve_node_style(primary, style_map) or tag_style
        else:
            ansi, badge_label, ns = None, None, tag_style

        if ansi:
            case       = 'matched'
            disp_badge = badge_label if (show_tag and badge_label) else None
        elif unmatched_ansi:
            case       = 'unmatched'
            ansi       = unmatched_ansi
            badge_label = unmatched_tag
            ns          = tag_style
            disp_badge  = unmatched_tag if (show_tag and unmatched_tag) else None
        elif dim_unmatched:
            case, disp_badge = 'dim', None
        else:
            case, disp_badge = 'plain', None

        render_info.append((case, ansi, badge_label, ns, pgroups, sgroups, name, type_str))
        pub_vws.append(_vis_pub_w(pgroups))
        mid_vws.append(_vis_mid_w(disp_badge, name, type_str))

    max_pub_w = max(pub_vws, default=0)
    max_mid_w = max(mid_vws, default=0)
    has_subs  = any(sub_groups.get(t, []) for t in all_topics)

    if topic_sort == 'group':
        render_info = _sort_by_group(render_info)

    # ── Pass 2: render with aligned columns ───────────────────────────────────
    for case, ansi, badge_label, ns, pgroups, sgroups, name, type_str in render_info:
        if case == 'empty':
            sys.stdout.write('\n')
            sys.stdout.flush()
            continue

        type_part = f' [\033[2m{type_str}{RESET}]' if type_str else ''

        # System topic: plain, indented to the topic-name column
        if case == 'system':
            col_offset = (max_pub_w + 1) if max_pub_w > 0 else 0
            sys.stdout.write(_INDENT + ' ' * col_offset + name + type_part + '\n')
            sys.stdout.flush()
            continue

        # Left column: pub blocks right-aligned in max_pub_w chars
        pub_vis = _vis_pub_w(pgroups)
        if max_pub_w > 0:
            pub_section = ' ' * (max_pub_w - pub_vis) + _count_blocks(pgroups) + ' '
        else:
            pub_section = ''

        # Middle column: [badge] colored_name [type]
        disp_badge = badge_label if (show_tag and badge_label) else None
        if case in ('matched', 'unmatched'):
            colored = f'\033[{ansi}m{name}{RESET}'
            mid = ((_badge(badge_label, ansi, ns) + ' ') if disp_badge else '') + colored + type_part
        elif case == 'dim':
            mid = f'\033[2m{name}{RESET}{type_part}'
        else:
            mid = name + type_part

        mid_vis = _vis_mid_w(disp_badge, name, type_str)

        # Right column: sub blocks, aligned across all lines
        sub_block = _count_blocks(sgroups)
        if has_subs and sub_block:
            sub_section = ' ' * (max_mid_w - mid_vis) + '  ' + sub_block
        else:
            sub_section = ''

        sys.stdout.write(_INDENT + pub_section + mid + sub_section + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
