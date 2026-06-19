"""YAML config loading, node resolution, and config merging."""

import fnmatch

import yaml

from lib.colors import _resolve_color
from lib.keywords import build_keyword_highlights


def load_config(config_path):
    """Parse dendROS.yaml and return (color_map, tag_map, mode_map, style_map, keyword_map, defaults).

    mode_map    holds per-node color_mode overrides set via group-level color_mode:.
    style_map   holds per-node tag_style overrides set via group-level tag_style:.
    keyword_map holds pre-compiled keyword highlights set via group-level highlight:.
    tag_map stores None for nodes whose group has show_tag: false.
    """
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    color_map   = {}
    tag_map     = {}
    mode_map    = {}
    style_map   = {}
    keyword_map = {}

    for group_name, group in (data.get('groups') or {}).items():
        ansi_code   = _resolve_color(group.get('color', ''))
        label       = group.get('label', '')
        group_mode  = group.get('color_mode')
        group_style = group.get('tag_style')
        group_kws   = build_keyword_highlights(
            group.get('highlight') or group.get('highlights') or [], ansi_code
        )
        if group.get('show_tag') is False:
            label = None
        for node in (group.get('nodes') or []):
            color_map[node] = ansi_code
            tag_map[node]   = label
            if group_mode is not None:
                mode_map[node] = group_mode
            if group_style is not None:
                style_map[node] = group_style
            if group_kws:
                keyword_map[node] = group_kws

    defaults = data.get('defaults') or {}
    return color_map, tag_map, mode_map, style_map, keyword_map, defaults


def merge_color_maps(primary_color, primary_tag, primary_mode, primary_style,
                     primary_keywords, secondaries):
    """Merge secondary (color, tag, mode, style, keywords) 5-tuples into primary.

    Primary wins all node-name conflicts.
    """
    merged_color    = dict(primary_color)
    merged_tag      = dict(primary_tag)
    merged_mode     = dict(primary_mode)
    merged_style    = dict(primary_style)
    merged_keywords = dict(primary_keywords)
    for sec_color, sec_tag, sec_mode, sec_style, sec_kw in secondaries:
        for node, code in sec_color.items():
            if node not in merged_color:
                merged_color[node] = code
                merged_tag[node]   = sec_tag.get(node)
                if node in sec_mode:
                    merged_mode[node] = sec_mode[node]
                if node in sec_style:
                    merged_style[node] = sec_style[node]
                if node in sec_kw:
                    merged_keywords[node] = sec_kw[node]
    return merged_color, merged_tag, merged_mode, merged_style, merged_keywords


def resolve_node(node_name, color_map, tag_map):
    """Return (ansi_code, label) for node_name.

    Lookup order:
      1. Exact full-path match  (/ns/talker  vs  /ns/talker)
      2. Exact basename match   (/ns/talker  vs  talker)
      3. Wildcard full-path     (/ns/talker  vs  /ns/talk*)
      4. Wildcard basename      (/ns/talker  vs  talk*)
    First matching pattern wins.
    """
    if node_name in color_map:
        return color_map[node_name], tag_map.get(node_name)
    basename = node_name.rsplit('/', 1)[-1]
    if basename in color_map:
        return color_map[basename], tag_map.get(basename)
    for pattern, code in color_map.items():
        if fnmatch.fnmatch(node_name, pattern):
            return code, tag_map.get(pattern)
    for pattern, code in color_map.items():
        if fnmatch.fnmatch(basename, pattern):
            return code, tag_map.get(pattern)
    return None, None


def resolve_node_mode(node_name, mode_map):
    """Return the per-node color_mode override from group-level color_mode:, or None."""
    if not mode_map:
        return None
    if node_name in mode_map:
        return mode_map[node_name]
    basename = node_name.rsplit('/', 1)[-1]
    if basename in mode_map:
        return mode_map[basename]
    for pattern, mode in mode_map.items():
        if fnmatch.fnmatch(node_name, pattern):
            return mode
    for pattern, mode in mode_map.items():
        if fnmatch.fnmatch(basename, pattern):
            return mode
    return None


def resolve_node_style(node_name, style_map):
    """Return the per-node tag_style override from group-level tag_style:, or None."""
    if not style_map:
        return None
    if node_name in style_map:
        return style_map[node_name]
    basename = node_name.rsplit('/', 1)[-1]
    if basename in style_map:
        return style_map[basename]
    for pattern, style in style_map.items():
        if fnmatch.fnmatch(node_name, pattern):
            return style
    for pattern, style in style_map.items():
        if fnmatch.fnmatch(basename, pattern):
            return style
    return None
