"""Node extraction from Python, XML and YAML ROS 2 launch files."""

import ast
import os
import xml.etree.ElementTree as ET

import yaml


def _ast_str(node):
    """Return the string value if node is a static string constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_nodes_from_python(content):
    """Parse a Python launch file and return a list of {name, package, namespace} dicts."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    results = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        is_node = (
            (isinstance(func, ast.Name) and func.id in ('Node', 'ComposableNode')) or
            (isinstance(func, ast.Attribute) and func.attr in ('Node', 'ComposableNode'))
        )
        if not is_node:
            continue

        kwargs = {}
        for kw in call.keywords:
            if kw.arg is None:
                continue
            val = _ast_str(kw.value)
            if val is not None:
                kwargs[kw.arg] = val

        name = kwargs.get('name') or kwargs.get('executable')
        if not name:
            continue

        results.append({
            'name': name,
            'package': kwargs.get('package'),
            'namespace': kwargs.get('namespace', ''),
        })

    return results


def extract_nodes_from_xml(content):
    """Parse an XML launch file and return a list of {name, package, namespace} dicts."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    results = []
    for elem in root.iter('node'):
        pkg   = elem.get('pkg') or elem.get('package')
        exec_ = elem.get('exec') or elem.get('executable')
        name  = elem.get('name') or exec_
        ns    = elem.get('namespace') or elem.get('ns') or ''
        if not name:
            continue
        results.append({'name': name, 'package': pkg, 'namespace': ns})

    return results


def _yaml_str(value):
    """Return value if it is a static string (no $(...) substitution), else None."""
    if isinstance(value, str) and '$(' not in value:
        return value
    return None


def _yaml_node_entry(attrs):
    """Build a {name, package, namespace} dict from a YAML node's attributes, or None."""
    if not isinstance(attrs, dict):
        return None
    name = _yaml_str(attrs.get('name')) or _yaml_str(attrs.get('exec'))
    if not name:
        return None
    return {
        'name': name,
        'package': _yaml_str(attrs.get('pkg')),
        'namespace': _yaml_str(attrs.get('namespace')) or '',
    }


def extract_nodes_from_yaml(content):
    """Parse a YAML launch file and return a list of {name, package, namespace} dicts."""
    try:
        tree = yaml.safe_load(content)
    except yaml.YAMLError:
        return []
    # The YAML frontend has a single `launch` root; anything else (e.g. a params file
    # kept in launch/) is not a launch file.
    if not isinstance(tree, dict) or list(tree) != ['launch']:
        return []

    results = []
    pending = [tree['launch']]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(reversed(item))
        elif isinstance(item, dict):
            for key, value in item.items():
                if key == 'node':
                    entry = _yaml_node_entry(value)
                    if entry:
                        results.append(entry)
                elif key == 'composable_node':
                    for attrs in value if isinstance(value, list) else [value]:
                        entry = _yaml_node_entry(attrs)
                        if entry:
                            results.append(entry)
                if isinstance(value, (dict, list)):
                    pending.append(value)

    return results


def scan_launch_file(path):
    """Dispatch to the correct parser based on file extension."""
    try:
        with open(path, 'r', errors='replace') as f:
            content = f.read()
    except OSError:
        return []

    ext = os.path.splitext(path)[1].lower()
    if ext == '.xml':
        return extract_nodes_from_xml(content)
    if ext == '.py':
        return extract_nodes_from_python(content)
    if ext in ('.yaml', '.yml'):
        return extract_nodes_from_yaml(content)
    return []
