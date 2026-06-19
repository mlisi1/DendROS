"""Config YAML generation and merging for dendros init."""

import re

import yaml

_STOCK_PALETTE = [
    'blue', 'green', 'yellow', 'magenta', 'cyan',
    'light blue', 'light green', 'bold magenta', 'red', 'bold cyan',
]


def make_label(pkg_name):
    """Generate a short uppercase label from a package name."""
    words = [re.sub(r'\d+', '', w) for w in re.split(r'[_-]', pkg_name) if w]
    words = [w for w in words if w]
    if not words:
        return pkg_name[:3].upper()
    if len(words) == 1:
        return words[0][:3].upper()
    return ''.join(w[0] for w in words[:4]).upper()


def _bold_color(color):
    """Prepend 'bold ' to a palette color string if not already bold."""
    if not color or color == 'null' or 'bold' in color:
        return color
    return 'bold ' + color


def write_config(path, node_groups, use_palette=True, use_bold=False, use_label=False):
    """Write a fresh dendROS.yaml with one group per source package.

    use_palette=True  — assign cycling colors from _STOCK_PALETTE
    use_palette=False — set color: null (passthrough; user fills in later)
    use_bold=True     — prefix every palette color with 'bold'
    use_label=False   — write label: "" (entry present; user fills in manually)
    use_label=True    — auto-generate a short label via make_label()
    """
    lines = ['groups:'] if node_groups else ['groups: {}']
    for i, (src_pkg, nodes) in enumerate(sorted(node_groups.items())):
        raw   = _STOCK_PALETTE[i % len(_STOCK_PALETTE)] if use_palette else 'null'
        color = _bold_color(raw) if use_bold else raw
        label = make_label(src_pkg) if use_label else ''
        lines += [
            f'  {src_pkg}:',
            f'    color: {color}',
            f'    label: "{label}"',
            f'    nodes:',
        ]
        for node in sorted(nodes):
            lines.append(f'      - {node}')
    lines += ['', 'defaults:', '  color_mode: tag_only',
              '  show_group_tag: true', '  unmatched_color: null', '']
    with open(path, 'w') as f:
        f.write('\n'.join(lines))


def merge_config(path, node_groups, use_bold=False, use_label=False):
    """Add nodes not already present in the existing config. Returns number of nodes added."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    existing_nodes = {
        n
        for group in (data.get('groups') or {}).values()
        for n in (group.get('nodes') or [])
    }

    truly_new = {
        pkg: {n for n in names if n not in existing_nodes}
        for pkg, names in node_groups.items()
    }
    truly_new = {k: v for k, v in truly_new.items() if v}
    if not truly_new:
        return 0

    groups = data.setdefault('groups', {})
    palette_start = len(groups)
    added = 0
    for i, (src_pkg, nodes) in enumerate(truly_new.items()):
        if src_pkg in groups:
            existing = groups[src_pkg].setdefault('nodes', [])
            for n in sorted(nodes):
                if n not in existing:
                    existing.append(n)
                    added += 1
        else:
            raw   = _STOCK_PALETTE[(palette_start + i) % len(_STOCK_PALETTE)]
            color = _bold_color(raw) if use_bold else raw
            label = make_label(src_pkg) if use_label else ''
            groups[src_pkg] = {
                'color': color,
                'label': label,
                'nodes': sorted(nodes),
            }
            added += len(nodes)

    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return added
