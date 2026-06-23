#!/usr/bin/env python3
"""Colorize ros2 node info output."""

import json
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
import lib.ros_graph as ros_graph

# "  Section Name:" — two leading spaces, words, colon
_SECTION_RE = re.compile(r'^  ([A-Za-z][A-Za-z ]*):$')

# Output sections: entries colored with the node's own color (no tag)
_OUTPUT_SECTIONS = {'Publishers', 'Service Servers', 'Action Servers'}

# Input sections: entries colored with the publishing node's color
_INPUT_SECTIONS = {'Subscribers'}


# ── color/config loading (shared with dendros_node_list) ─────────────────────

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


# ── rendering helpers ─────────────────────────────────────────────────────────

def _badge(label, ansi_code, style):
    if style == 'inverted':
        return f'\033[{ansi_code};7m[{label}]{RESET}'
    return f'\033[{ansi_code}m[{label}]{RESET}'


def _format_entry(raw, ansi_code=None):
    """Color the name part of an entry line; always dim the type annotation."""
    stripped = raw.lstrip()
    indent   = raw[:len(raw) - len(stripped)]

    if stripped == '(None)':
        return f'{indent}\033[2m(None){RESET}'

    if ': ' in stripped:
        name, type_str = stripped.split(': ', 1)
        if ansi_code:
            return f'{indent}\033[{ansi_code}m{name}{RESET}: \033[2m{type_str}{RESET}'
        return f'{indent}{name}: \033[2m{type_str}{RESET}'

    if ansi_code:
        return f'\033[{ansi_code}m{raw}{RESET}'
    return raw


# ── graph-aware subscriber coloring ──────────────────────────────────────────

def _collect_input_topics(lines):
    """Return set of topic names appearing under _INPUT_SECTIONS."""
    topics = set()
    current_section = None
    past_first = False
    for raw in lines:
        if not past_first:
            if raw:
                past_first = True
            continue
        m = _SECTION_RE.match(raw)
        if m:
            current_section = m.group(1)
            continue
        if current_section in _INPUT_SECTIONS and raw.strip() and raw.strip() != '(None)':
            stripped = raw.strip()
            if ': ' in stripped:
                topics.add(stripped.split(': ', 1)[0])
    return topics


def _build_topic_color_map(topics, color_map, tag_map):
    """Return {topic: ansi_code} by querying the ROS 2 graph for publishers.

    In tests, set DENDROS_TOPIC_PUBLISHERS to a JSON dict
    {topic: [node_basename, ...]} to skip the live graph query.
    """
    if not color_map or not topics:
        return {}

    override = os.environ.get('DENDROS_TOPIC_PUBLISHERS')
    if override is not None:
        try:
            topic_to_nodes = json.loads(override)
        except (json.JSONDecodeError, ValueError):
            topic_to_nodes = {}
    else:
        topic_to_nodes = ros_graph.get_topic_publishers(topics)

    result = {}
    for topic, pub_nodes in topic_to_nodes.items():
        if not pub_nodes:
            continue
        # First publisher wins (multiple publishers: future work)
        code, _ = resolve_node(pub_nodes[0], color_map, tag_map)
        if code:
            result[topic] = code
    return result


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    cfg = load_global_config()
    show_tag       = cfg['show_group_tag']
    tag_position   = cfg['tag_position']
    tag_style      = cfg['tag_style']
    unmatched_clr  = cfg['unmatched_color']
    dim_unmatched  = cfg['dim_unmatched']
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

    # Buffer stdin — needed to pre-scan subscriber topics before rendering
    lines = [line.rstrip('\n') for line in sys.stdin]

    # Pre-scan input topics and query the graph once
    input_topics     = _collect_input_topics(lines)
    topic_color_map  = _build_topic_color_map(input_topics, color_map, tag_map)

    # Render
    ansi_code       = None
    current_section = None
    first_line      = True

    for raw in lines:
        # ── node name (first non-empty line) ──────────────────────────────────
        if first_line:
            if not raw:
                sys.stdout.write('\n')
                sys.stdout.flush()
                continue
            first_line = False
            node_name = raw.strip()
            ansi_code, label = resolve_node(node_name, color_map, tag_map)

            if ansi_code:
                node_style   = resolve_node_style(node_name, style_map) or tag_style
                colored_name = f'\033[{ansi_code}m{raw}{RESET}'
                if show_tag and label:
                    badge = _badge(label, ansi_code, node_style)
                    out = (f'{badge} {colored_name}' if tag_position == 'before'
                           else f'{colored_name} {badge}')
                else:
                    out = colored_name
            elif unmatched_ansi:
                out = f'\033[{unmatched_ansi}m{raw}{RESET}'
            elif dim_unmatched:
                out = f'\033[2m{raw}{RESET}'
            else:
                out = raw
            sys.stdout.write(out + '\n')
            sys.stdout.flush()
            continue

        # ── section header ────────────────────────────────────────────────────
        m = _SECTION_RE.match(raw)
        if m:
            current_section = m.group(1)
            sys.stdout.write(f'\033[1m{raw}{RESET}\n')
            sys.stdout.flush()
            continue

        # ── content line ──────────────────────────────────────────────────────
        if raw.strip():
            if current_section in _OUTPUT_SECTIONS and ansi_code:
                out = _format_entry(raw, ansi_code)
            elif current_section in _INPUT_SECTIONS:
                stripped = raw.strip()
                topic    = stripped.split(': ', 1)[0] if ': ' in stripped else None
                out      = _format_entry(raw, topic_color_map.get(topic) if topic else None)
            else:
                out = _format_entry(raw)
        else:
            out = raw

        sys.stdout.write(out + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
