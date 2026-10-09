#!/usr/bin/env python3
"""dendros init — scaffold a dendROS.yaml config from a ROS 2 package's launch files."""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.colors import DENDROS_TAG, RESET

try:
    import yaml
except ImportError:
    print(f'{DENDROS_TAG} PyYAML required: pip3 install pyyaml', file=sys.stderr)
    sys.exit(1)

from lib.config_writer import write_config, merge_config
from lib.build_modifier import modify_cmake, modify_setup_py, modify_setup_cfg
from lib.discovery import (
    list_launch_files, extract_included_packages,
    find_pkg_launch_files, find_pkg_in_source_tree,
)
from lib.global_config import load_global_config
from lib.node_extractor import scan_launch_file


# ── output ────────────────────────────────────────────────────────────────────
# Severity colors match ROS 2's own console output (rcutils): INFO in the terminal's default
# color, WARN yellow, ERROR red — so init's messages read like the logs they sit next to.
_WARN_COLOR  = '\033[33m'
_ERROR_COLOR = '\033[31m'

def _info(msg):
    print(f'{DENDROS_TAG} {msg}', flush=True)  # keep order with stderr when piped

def _warn(msg):
    print(f'{DENDROS_TAG} {_WARN_COLOR}{msg}{RESET}', file=sys.stderr)

def _error(msg):
    print(f'{DENDROS_TAG} {_ERROR_COLOR}{msg}{RESET}', file=sys.stderr)


# ── package detection ─────────────────────────────────────────────────────────

def find_package_root(cwd=None):
    """The package root is the current directory itself, when it holds a package.xml — never
    an ancestor: walking up would let a run from some unrelated subfolder silently write a
    config (and patch the build files) of whatever package happens to enclose it."""
    current = Path(cwd) if cwd else Path.cwd()
    return current if (current / 'package.xml').exists() else None


def find_enclosing_package(cwd=None):
    """Nearest ancestor directory holding a package.xml, or None — only used to point the
    user at the right directory when init is run from inside a package's subfolder."""
    current = Path(cwd) if cwd else Path.cwd()
    for directory in current.parents:
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


# ── node collection ───────────────────────────────────────────────────────────

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
    workspace_src_dir = local_launch_dir.parent.parent

    local_files = list_launch_files(str(local_launch_dir))
    pending_pkgs = []

    for lf in local_files:
        nodes = scan_launch_file(lf)
        _info(f'  {os.path.basename(lf)}: {len(nodes)} node(s)')
        for n in nodes:
            src = n.get('package') or pkg_name
            node_groups.setdefault(src, set()).add(n['name'])
        if recursive:
            for inc in extract_included_packages(lf):
                if inc not in scanned:
                    pending_pkgs.append(inc)

    if recursive:
        queue = list(dict.fromkeys(pending_pkgs))
        if queue:
            _info(f'recursive: found references to: {", ".join(queue)}')
        else:
            _warn('recursive: no include references found in local launch files')
        while queue:
            inc_pkg = queue.pop(0)
            if inc_pkg in scanned:
                continue
            scanned.add(inc_pkg)

            inc_files = find_pkg_launch_files(inc_pkg)
            source = 'install'
            if not inc_files:
                inc_files = find_pkg_in_source_tree(inc_pkg, workspace_src_dir)
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
                for dep in extract_included_packages(lf):
                    if dep not in scanned:
                        queue.append(dep)

    return node_groups


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    recursive      = '--recursive' in argv or '-r' in argv
    use_label_flag = '--labels'    in argv or '-l' in argv

    cfg = load_global_config()
    init_modify_build = cfg.get('init_modify_build', True)
    init_on_existing  = cfg.get('init_on_existing',  'abort')
    init_color        = cfg.get('init_color',         'palette')
    use_palette       = init_color == 'palette'
    use_bold          = cfg.get('init_color_bold', False)
    use_label         = use_label_flag or cfg.get('init_label', False)

    pkg_root = find_package_root()
    if pkg_root is None:
        enclosing = find_enclosing_package()
        if enclosing is not None:
            _error(f'not a package root (no package.xml here). This is inside '
                   f'{get_package_name(enclosing) or "a package"}: run `dendros init` from {enclosing}')
        else:
            _error('not a ROS 2 package (no package.xml here). Run `dendros init` from the '
                   'root of the package whose launch files you want to scan.')
        sys.exit(1)

    pkg_name = get_package_name(pkg_root)
    if not pkg_name:
        _error(f'could not read package name from {pkg_root / "package.xml"}.')
        sys.exit(1)

    _info(f'package: {pkg_name}  root: {pkg_root}')

    config_dir  = pkg_root / 'config'
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
        # Nothing to color: don't leave an empty config/ + dendROS.yaml (and patched build
        # files) behind in the package.
        _error('no nodes found in the launch files — nothing written.'
               + ('' if recursive or not launch_dir.exists()
                  else ' Try --recursive if they come from included launch files.'))
        sys.exit(1)

    config_dir.mkdir(parents=True, exist_ok=True)
    existed_before = config_path.exists()

    if init_on_existing == 'merge' and existed_before:
        added = merge_config(
            str(config_path), {k: list(v) for k, v in node_groups.items()},
            use_bold=use_bold, use_label=use_label,
        )
        _info(f'merged {added} new node(s) into {config_path}')
    else:
        write_config(
            str(config_path), {k: list(v) for k, v in node_groups.items()},
            use_palette=use_palette, use_bold=use_bold, use_label=use_label,
        )
        _info(f'{"updated" if existed_before else "created"} {config_path}')

    if init_modify_build:
        cmake     = pkg_root / 'CMakeLists.txt'
        setup_py  = pkg_root / 'setup.py'
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
