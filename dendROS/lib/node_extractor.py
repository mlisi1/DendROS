"""Node extraction from Python and XML ROS 2 launch files."""

import ast
import os
import xml.etree.ElementTree as ET


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
    return []
