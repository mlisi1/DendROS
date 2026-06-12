#!/usr/bin/env python3
"""dendros init — scaffold a dendROS.yaml config from a ROS 2 package's launch files."""

import ast
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[dendROS] PyYAML required: pip3 install pyyaml", file=sys.stderr)
    sys.exit(1)

# ── constants ─────────────────────────────────────────────────────────────────

_STOCK_PALETTE = [
    'blue', 'green', 'yellow', 'magenta', 'cyan',
    'light blue', 'light green', 'bold magenta', 'red', 'bold cyan',
]

_GLOBAL_CONFIG_RELPATH = '~/.config/dendROS/defaults.yaml'

_PY_INCLUDE_RE = re.compile(
    r'''(?:get_package_share_directory|FindPackageShare)\s*\(\s*['"]([a-zA-Z0-9_.-]+)['"]\s*\)'''
)
_XML_INCLUDE_RE = re.compile(r'\$\(find-pkg-share\s+([a-zA-Z0-9_.-]+)\)')

_CMAKE_INSTALL_SNIPPET = (
    '\ninstall(DIRECTORY config/\n'
    '  DESTINATION share/${PROJECT_NAME}\n'
    ')\n'
)

# ── output ────────────────────────────────────────────────────────────────────

def _info(msg):
    print(f'\033[35;1m[dendROS]\033[0m {msg}')

def _warn(msg):
    print(f'\033[33;1m[dendROS]\033[0m {msg}', file=sys.stderr)

def _error(msg):
    print(f'\033[31;1m[dendROS]\033[0m {msg}', file=sys.stderr)

# ── global config ─────────────────────────────────────────────────────────────

def _load_global_config():
    """Load init-relevant settings from ~/.config/dendROS/defaults.yaml."""
    defaults = {'init_modify_build': True, 'init_on_existing': 'abort', 'init_color': 'palette',
                'init_color_bold': False}
    path = os.path.expanduser(_GLOBAL_CONFIG_RELPATH)
    if not os.path.isfile(path):
        return defaults
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return {**defaults, **{k: v for k, v in data.items() if k in defaults}}
    except Exception:
        return defaults

# ── label generation ──────────────────────────────────────────────────────────

def make_label(pkg_name):
    """Generate a short uppercase label from a package name."""
    words = [re.sub(r'\d+', '', w) for w in re.split(r'[_-]', pkg_name) if w]
    words = [w for w in words if w]
    if not words:
        return pkg_name[:3].upper()
    if len(words) == 1:
        return words[0][:3].upper()
    return ''.join(w[0] for w in words[:4]).upper()

# ── node extraction ───────────────────────────────────────────────────────────

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

        # name= takes priority; fall back to executable=
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
        pkg = elem.get('pkg') or elem.get('package')
        exec_ = elem.get('exec') or elem.get('executable')
        name = elem.get('name') or exec_
        ns = elem.get('namespace') or elem.get('ns') or ''
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


def _extract_included_packages(path):
    """Return package names referenced via include directives in a launch file."""
    try:
        with open(path, 'r', errors='replace') as f:
            content = f.read()
    except OSError:
        return []

    ext = os.path.splitext(path)[1].lower()
    if ext == '.xml':
        raw = _XML_INCLUDE_RE.findall(content)
    elif ext == '.py':
        raw = _PY_INCLUDE_RE.findall(content)
    else:
        raw = _PY_INCLUDE_RE.findall(content) + _XML_INCLUDE_RE.findall(content)

    seen, result = set(), []
    for p in raw:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _list_launch_files(launch_dir):
    """Return .py and .xml files from a launch directory."""
    if not os.path.isdir(launch_dir):
        return []
    return [
        os.path.join(launch_dir, f)
        for f in sorted(os.listdir(launch_dir))
        if f.endswith('.py') or f.endswith('.xml')
    ]


def _find_pkg_launch_files(pkg_name):
    """Locate the installed launch files for an external package."""
    def _probe(prefix):
        d = os.path.join(prefix, 'share', pkg_name, 'launch')
        files = _list_launch_files(d)
        return files if files else None

    try:
        r = subprocess.run(
            ['ros2', 'pkg', 'prefix', pkg_name],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0:
            files = _probe(r.stdout.strip())
            if files:
                return files
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    for prefix in os.environ.get('AMENT_PREFIX_PATH', '').split(':'):
        if not prefix:
            continue
        files = _probe(prefix)
        if files:
            return files

    return []


def _find_pkg_in_source_tree(pkg_name, workspace_src_dir):
    """Look for a package's launch/ directory as a sibling in the same src/ folder."""
    candidate = os.path.join(str(workspace_src_dir), pkg_name, 'launch')
    return _list_launch_files(candidate)


def collect_nodes(local_launch_dir, pkg_name, recursive=False):
    """Scan launch files and return {source_package: set_of_node_names}.

    With recursive=True, follows include references into external packages (BFS,
    cycle-safe on package name). Searches the install tree (AMENT_PREFIX_PATH /
    ros2 pkg prefix) and, as a fallback, sibling directories in the same source
    workspace (useful when packages are not yet installed).
    """
    node_groups = {}
    scanned = {pkg_name}

    local_launch_dir = Path(local_launch_dir)
    # Heuristic workspace src dir: grandparent of launch/ (e.g. ws/src)
    workspace_src_dir = local_launch_dir.parent.parent

    local_files = _list_launch_files(str(local_launch_dir))
    pending_pkgs = []

    for lf in local_files:
        nodes = scan_launch_file(lf)
        _info(f'  {os.path.basename(lf)}: {len(nodes)} node(s)')
        for n in nodes:
            src = n.get('package') or pkg_name
            node_groups.setdefault(src, set()).add(n['name'])
        if recursive:
            for inc in _extract_included_packages(lf):
                if inc not in scanned:
                    pending_pkgs.append(inc)

    if recursive:
        queue = list(dict.fromkeys(pending_pkgs))  # deduplicate, preserve order
        if queue:
            _info(f'recursive: found references to: {", ".join(queue)}')
        else:
            _warn('recursive: no include references found in local launch files')
        while queue:
            inc_pkg = queue.pop(0)
            if inc_pkg in scanned:
                continue
            scanned.add(inc_pkg)

            inc_files = _find_pkg_launch_files(inc_pkg)
            source = 'install'
            if not inc_files:
                inc_files = _find_pkg_in_source_tree(inc_pkg, workspace_src_dir)
                source = 'source'
            if not inc_files:
                _warn(f'  {inc_pkg}: not found (not in install tree or source siblings)')
                continue

            for lf in inc_files:
                nodes = scan_launch_file(lf)
                _info(f'  {inc_pkg}/{os.path.basename(lf)} [{source}]: {len(nodes)} node(s)')
                for n in nodes:
                    src = n.get('package') or inc_pkg
                    node_groups.setdefault(src, set()).add(n['name'])
                for dep in _extract_included_packages(lf):
                    if dep not in scanned:
                        queue.append(dep)

    return node_groups

# ── config writing ────────────────────────────────────────────────────────────

def _bold_color(color):
    """Prepend 'bold ' to a palette color string if not already bold."""
    if not color or color == 'null' or 'bold' in color:
        return color
    return 'bold ' + color


def write_config(path, node_groups, use_palette=True, use_bold=False):
    """Write a fresh dendROS.yaml with one group per source package.

    use_palette=True  — assign cycling colors from _STOCK_PALETTE
    use_palette=False — set color: null (passthrough; user fills in later)
    use_bold=True     — prefix every palette color with 'bold'
    Labels are never written; the user adds them manually if desired.
    """
    lines = ['groups:'] if node_groups else ['groups: {}']
    for i, (src_pkg, nodes) in enumerate(sorted(node_groups.items())):
        raw = _STOCK_PALETTE[i % len(_STOCK_PALETTE)] if use_palette else 'null'
        color = _bold_color(raw) if use_bold else raw
        lines += [
            f'  {src_pkg}:',
            f'    color: {color}',
            f'    nodes:',
        ]
        for node in sorted(nodes):
            lines.append(f'      - {node}')
    lines += ['', 'defaults:', '  color_mode: tag_only',
              '  show_group_tag: true', '  unmatched_color: null', '']
    with open(path, 'w') as f:
        f.write('\n'.join(lines))


def merge_config(path, node_groups, use_bold=False):
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
            raw = _STOCK_PALETTE[(palette_start + i) % len(_STOCK_PALETTE)]
            color = _bold_color(raw) if use_bold else raw
            groups[src_pkg] = {
                'color': color,
                'nodes': sorted(nodes),
            }
            added += len(nodes)

    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return added

# ── build system modifications ────────────────────────────────────────────────

def modify_cmake(cmake_path):
    """Add config install block to CMakeLists.txt. Returns True if the file was changed."""
    with open(cmake_path) as f:
        content = f.read()

    if re.search(r'install\s*\(\s*DIRECTORY\s+config[/\s)]', content):
        return False

    new_content, n = re.subn(
        r'(\nament_package\s*\(\s*\))',
        _CMAKE_INSTALL_SNIPPET + r'\1',
        content,
    )
    if n == 0:
        new_content = content.rstrip('\n') + '\n' + _CMAKE_INSTALL_SNIPPET

    with open(cmake_path, 'w') as f:
        f.write(new_content)
    return True


def modify_setup_py(setup_py_path, pkg_name):
    """Add config/dendROS.yaml to data_files in setup.py. Returns True if changed."""
    with open(setup_py_path) as f:
        content = f.read()

    if re.search(r'[\'"]config[/\\]dendROS\.yaml[\'"]', content):
        return False

    m = re.search(r'data_files\s*=\s*\[', content)
    if not m:
        return False

    # Find the closing ] by bracket counting
    depth, i = 1, m.end()
    while i < len(content) and depth > 0:
        if content[i] == '[':
            depth += 1
        elif content[i] == ']':
            depth -= 1
        i += 1
    if depth != 0:
        return False

    entry = (
        f"        (os.path.join('share', '{pkg_name}', 'config'),"
        f" ['config/dendROS.yaml']),\n"
    )
    new_content = content[:i - 1] + entry + content[i - 1:]

    if 'import os' not in new_content and 'from os' not in new_content:
        new_content = 'import os\n' + new_content

    with open(setup_py_path, 'w') as f:
        f.write(new_content)
    return True


def modify_setup_cfg(setup_cfg_path, pkg_name):
    """Add config data_files entry to setup.cfg. Returns True if changed."""
    with open(setup_cfg_path) as f:
        content = f.read()

    if 'dendROS.yaml' in content:
        return False

    entry = f'share/{pkg_name}/config =\n    config/dendROS.yaml\n'

    m = re.search(r'\[options\.data_files\]', content)
    if m:
        rest = content[m.end():]
        next_sec = re.search(r'\n\[', rest)
        insert_pos = m.end() + (next_sec.start() if next_sec else len(rest))
        if not content[insert_pos - 1:insert_pos] == '\n':
            entry = '\n' + entry
        new_content = content[:insert_pos] + entry + content[insert_pos:]
    else:
        new_content = content.rstrip('\n') + '\n\n[options.data_files]\n' + entry

    with open(setup_cfg_path, 'w') as f:
        f.write(new_content)
    return True

# ── package detection ─────────────────────────────────────────────────────────

def find_package_root(cwd=None):
    """Walk up from cwd (or Path.cwd()) to find the directory containing package.xml."""
    current = Path(cwd) if cwd else Path.cwd()
    for directory in [current] + list(current.parents):
        if (directory / 'package.xml').exists():
            return directory
    return None


def get_package_name(pkg_root):
    """Read the package name from package.xml using ElementTree."""
    try:
        tree = ET.parse(str(pkg_root / 'package.xml'))
        elem = tree.getroot().find('name')
        return elem.text.strip() if elem is not None else None
    except ET.ParseError:
        return None

# ── main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    recursive = '--recursive' in argv

    cfg = _load_global_config()
    init_modify_build = cfg.get('init_modify_build', True)
    init_on_existing = cfg.get('init_on_existing', 'abort')
    init_color = cfg.get('init_color', 'palette')
    use_palette = init_color == 'palette'
    use_bold = cfg.get('init_color_bold', False)

    pkg_root = find_package_root()
    if pkg_root is None:
        _error('no package.xml found in the current directory or any parent.')
        sys.exit(1)

    pkg_name = get_package_name(pkg_root)
    if not pkg_name:
        _error(f'could not read package name from {pkg_root / "package.xml"}.')
        sys.exit(1)

    _info(f'package: {pkg_name}  root: {pkg_root}')

    config_dir = pkg_root / 'config'
    config_path = config_dir / 'dendROS.yaml'

    if config_path.exists():
        if init_on_existing == 'abort':
            _error(
                f'{config_path} already exists. '
                'Remove it or change init_on_existing via `dendros config`.'
            )
            sys.exit(1)
        elif init_on_existing == 'overwrite':
            _warn(f'overwriting {config_path}')

    launch_dir = pkg_root / 'launch'
    if not launch_dir.exists():
        _warn(f'no launch/ directory found in {pkg_root}')

    _info(f'scanning {"(recursive) " if recursive else ""}launch files…')
    node_groups = collect_nodes(launch_dir, pkg_name, recursive=recursive)

    total = sum(len(v) for v in node_groups.values())
    _info(f'found {total} node(s) in {len(node_groups)} group(s)')
    if total == 0:
        _warn('no nodes found — the generated config will be empty.')

    config_dir.mkdir(parents=True, exist_ok=True)
    existed_before = config_path.exists()

    if init_on_existing == 'merge' and existed_before:
        added = merge_config(str(config_path), {k: list(v) for k, v in node_groups.items()}, use_bold=use_bold)
        _info(f'merged {added} new node(s) into {config_path}')
    else:
        write_config(str(config_path), {k: list(v) for k, v in node_groups.items()}, use_palette=use_palette, use_bold=use_bold)
        _info(f'{"updated" if existed_before else "created"} {config_path}')

    if init_modify_build:
        cmake = pkg_root / 'CMakeLists.txt'
        setup_py = pkg_root / 'setup.py'
        setup_cfg = pkg_root / 'setup.cfg'

        if cmake.exists():
            if modify_cmake(str(cmake)):
                _info('updated CMakeLists.txt (added config install)')
            else:
                _info('CMakeLists.txt already installs config/')

        if setup_py.exists():
            if modify_setup_py(str(setup_py), pkg_name):
                _info('updated setup.py (added config to data_files)')
            else:
                _info('setup.py already references config/dendROS.yaml')

        if setup_cfg.exists():
            if modify_setup_cfg(str(setup_cfg), pkg_name):
                _info('updated setup.cfg (added config to data_files)')
            else:
                _info('setup.cfg already references config/dendROS.yaml')

    _info(f'done. Edit {config_path} to customize colors and groups.')


if __name__ == '__main__':
    main()
