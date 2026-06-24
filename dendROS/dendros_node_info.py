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

_SECTION_RE = re.compile(r'^  ([A-Za-z][A-Za-z ]*):$')

_OUTPUT_SECTIONS    = {'Publishers', 'Service Servers', 'Action Servers'}
_INPUT_SECTION_KIND = {
    'Subscribers':    'topics',
    'Service Clients': 'services',
    'Action Clients':  'actions',
}


# ── color/config loading ──────────────────────────────────────────────────────

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


def _item_name(stripped):
    """Extract item name from 'name: type' or 'name [type]'; None for (None)."""
    if stripped == '(None)':
        return None
    if ': ' in stripped:
        return stripped.split(': ', 1)[0]
    if ' [' in stripped:
        return stripped.split(' [', 1)[0]
    if stripped.startswith('/'):
        return stripped
    return None


def _nodes_to_groups(nodes, color_map, tag_map):
    """Group nodes by color code, summing counts. Returns [(code, count), ...]."""
    counts = {}
    for node in nodes:
        code, _ = resolve_node(node, color_map, tag_map)
        if code:
            counts[code] = counts.get(code, 0) + 1
    return list(counts.items())


def _nodes_to_codes(nodes, color_map, tag_map):
    """Deduplicated [code, ...] — used for service/action client extra providers."""
    codes = []
    for node in nodes:
        code, _ = resolve_node(node, color_map, tag_map)
        if code and code not in codes:
            codes.append(code)
    return codes


def _format_entry(raw, ansi_code=None, trail_groups=(), post_codes=()):
    """Format a ros2 node info entry line.

    ansi_code    — ANSI code to color the item name (None = no color).
    trail_groups — [(code, count), ...] rendered as inverted-video counts AFTER type.
                   Used for topic subscriber/publisher indicators.
    post_codes   — [code, ...] rendered as trailing ■ squares AFTER type.
                   Used for service/action extra providers.

    Handles both 'name: type' and 'name [type]' entry formats.
    """
    stripped = raw.lstrip()
    indent   = raw[:len(raw) - len(stripped)]

    if stripped == '(None)':
        return f'{indent}\033[2m(None){RESET}'

    trailing = ''
    if trail_groups:
        trailing += '  ' + ' '.join(f'\033[{c};7m{n}\033[0m' for c, n in trail_groups)
    if post_codes:
        trailing += '  ' + ' '.join(f'\033[{c}m■{RESET}' for c in post_codes)

    if ': ' in stripped:
        name, type_str = stripped.split(': ', 1)
        if ansi_code:
            return (f'{indent}\033[{ansi_code}m{name}{RESET}: '
                    f'\033[2m{type_str}{RESET}{trailing}')
        return f'{indent}{name}: \033[2m{type_str}{RESET}{trailing}'

    if ' [' in stripped:
        name, rest = stripped.split(' [', 1)
        type_str = rest.rstrip(']')
        if ansi_code:
            return (f'{indent}\033[{ansi_code}m{name}{RESET} '
                    f'[\033[2m{type_str}{RESET}]{trailing}')
        return f'{indent}{name} [\033[2m{type_str}{RESET}]{trailing}'

    if ansi_code:
        return f'{indent}\033[{ansi_code}m{stripped}{RESET}{trailing}'
    return f'{indent}{stripped}{trailing}'


# ── graph-aware item collection ───────────────────────────────────────────────

def _collect_input_items(lines):
    """Scan buffered lines; return {'topics': set, 'services': set, 'actions': set}."""
    items = {'topics': set(), 'services': set(), 'actions': set()}
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
        kind = _INPUT_SECTION_KIND.get(current_section)
        if kind and raw.strip():
            name = _item_name(raw.strip())
            if name:
                items[kind].add(name)
    return items


def _collect_output_topics(lines):
    """Return the set of topic names listed in the Publishers section."""
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
        if current_section == 'Publishers' and raw.strip():
            name = _item_name(raw.strip())
            if name:
                topics.add(name)
    return topics


def _fetch_from_env(item_set, env_key):
    """Return {item: [node, ...]} from env var JSON, or None to use live graph."""
    ov = os.environ.get(env_key)
    if ov is None:
        return None
    try:
        injected = json.loads(ov)
    except (json.JSONDecodeError, ValueError):
        injected = {}
    return {item: injected.get(item, []) for item in item_set}


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    cfg = load_global_config()
    show_tag       = cfg['show_tag_cli']
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

    lines = [line.rstrip('\n') for line in sys.stdin]

    input_items   = _collect_input_items(lines)
    output_topics = _collect_output_topics(lines)

    # ── fetch provider nodes (env vars → single live graph call) ─────────────
    sub_ov   = _fetch_from_env(input_items['topics'],   'DENDROS_TOPIC_PUBLISHERS')
    svc_ov   = _fetch_from_env(input_items['services'], 'DENDROS_SERVICE_SERVERS')
    act_ov   = _fetch_from_env(input_items['actions'],  'DENDROS_ACTION_SERVERS')
    psub_ov  = _fetch_from_env(output_topics,           'DENDROS_TOPIC_SUBSCRIBERS')

    sub_nodes  = sub_ov  or {}
    svc_nodes  = svc_ov  or {}
    act_nodes  = act_ov  or {}
    psub_nodes = psub_ov or {}

    # One rclpy session for anything not covered by env vars
    if color_map:
        live_topics   = input_items['topics']   if sub_ov  is None else set()
        live_services = input_items['services'] if svc_ov  is None else set()
        live_actions  = input_items['actions']  if act_ov  is None else set()
        live_psubs    = output_topics            if psub_ov is None else set()

        if live_topics or live_services or live_actions or live_psubs:
            try:
                raw = ros_graph.get_all_providers(
                    topics=live_topics, services=live_services,
                    actions=live_actions, pub_topics=live_psubs,
                )
                if sub_ov  is None:
                    sub_nodes  = {t: raw.get(t, []) for t in live_topics}
                if svc_ov  is None:
                    svc_nodes  = {s: raw.get(s, []) for s in live_services}
                if act_ov  is None:
                    act_nodes  = {a: raw.get(a, []) for a in live_actions}
                if psub_ov is None:
                    psub_nodes = {t: raw.get(ros_graph._PUB_SUB_PREFIX + t, [])
                                  for t in live_psubs}
            except Exception:
                pass

    # ── convert to display structures ─────────────────────────────────────────
    # Topics: grouped counts → inverted-video trailing indicators
    sub_groups = {t: _nodes_to_groups(sub_nodes.get(t, []),  color_map, tag_map)
                  for t in input_items['topics']}
    pub_groups = {t: _nodes_to_groups(psub_nodes.get(t, []), color_map, tag_map)
                  for t in output_topics}

    # Services/actions: flat code list → trailing ■ squares for extras
    svc_codes  = {s: _nodes_to_codes(svc_nodes.get(s, []), color_map, tag_map)
                  for s in input_items['services']}
    act_codes  = {a: _nodes_to_codes(act_nodes.get(a, []), color_map, tag_map)
                  for a in input_items['actions']}

    # ── render ────────────────────────────────────────────────────────────────
    ansi_code       = None
    current_section = None
    first_line      = True

    for raw in lines:
        # ── node name ─────────────────────────────────────────────────────────
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
            name = _item_name(raw.strip())

            if current_section in _OUTPUT_SECTIONS and ansi_code:
                groups = pub_groups.get(name, []) if (name and current_section == 'Publishers') else []
                out = _format_entry(raw, ansi_code, trail_groups=groups)

            elif current_section == 'Subscribers':
                groups  = sub_groups.get(name, []) if name else []
                primary = groups[0][0] if groups else None
                out = _format_entry(raw, primary, trail_groups=groups)

            elif current_section in ('Service Clients', 'Action Clients'):
                codes = (svc_codes if current_section == 'Service Clients'
                         else act_codes).get(name, []) if name else []
                out = _format_entry(raw, codes[0] if codes else None,
                                    post_codes=codes[1:])
            else:
                out = _format_entry(raw)
        else:
            out = raw

        sys.stdout.write(out + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    main()
