"""ROS package and launch file discovery utilities."""

import os
import re
import subprocess

# Launch file include patterns (shared between pipe and init)
_PY_INCLUDE_RE = re.compile(
    r'''(?:get_package_share_directory|FindPackageShare)\s*\(\s*['"]([a-zA-Z0-9_.-]+)['"]\s*\)'''
)
_XML_INCLUDE_RE = re.compile(r'\$\(find-pkg-share\s+([a-zA-Z0-9_.-]+)\)')


def extract_package_name(argv):
    """Return the package name from ros2 launch/run argv, skipping flags."""
    for arg in argv[1:]:
        if not arg.startswith('-'):
            return arg
    return None


def extract_launch_file(argv):
    """Return the launch file name (second non-flag positional) from ros2 launch argv."""
    if not argv or argv[0] != 'launch':
        return None
    positionals = [a for a in argv[1:] if not a.startswith('-')]
    return positionals[1] if len(positionals) >= 2 else None


def find_config(pkg_name):
    """Return path to dendROS.yaml for pkg_name, or None if not found."""
    if not pkg_name:
        return None

    try:
        result = subprocess.run(
            ['ros2', 'pkg', 'prefix', pkg_name],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            prefix = result.stdout.strip()
            candidate = os.path.join(prefix, 'share', pkg_name, 'config', 'dendROS.yaml')
            if os.path.isfile(candidate):
                return candidate
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    for prefix in os.environ.get('AMENT_PREFIX_PATH', '').split(':'):
        if not prefix:
            continue
        candidate = os.path.join(prefix, 'share', pkg_name, 'config', 'dendROS.yaml')
        if os.path.isfile(candidate):
            return candidate

    return None


def find_launch_file(pkg_name, launch_file_name):
    """Return path to the launch file for pkg_name, or None if not found."""
    if not pkg_name or not launch_file_name:
        return None

    try:
        result = subprocess.run(
            ['ros2', 'pkg', 'prefix', pkg_name],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            prefix = result.stdout.strip()
            candidate = os.path.join(prefix, 'share', pkg_name, 'launch', launch_file_name)
            if os.path.isfile(candidate):
                return candidate
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    for prefix in os.environ.get('AMENT_PREFIX_PATH', '').split(':'):
        if not prefix:
            continue
        candidate = os.path.join(prefix, 'share', pkg_name, 'launch', launch_file_name)
        if os.path.isfile(candidate):
            return candidate

    return None


def extract_included_packages(launch_file_path):
    """Return package names referenced in a launch file (Python or XML), deduplicated."""
    if not launch_file_path or not os.path.isfile(launch_file_path):
        return []
    try:
        with open(launch_file_path, 'r', errors='replace') as f:
            content = f.read()
    except OSError:
        return []

    ext = os.path.splitext(launch_file_path)[1].lower()
    if ext == '.xml':
        raw = _XML_INCLUDE_RE.findall(content)
    elif ext == '.py':
        raw = _PY_INCLUDE_RE.findall(content)
    else:
        raw = _PY_INCLUDE_RE.findall(content) + _XML_INCLUDE_RE.findall(content)

    seen = set()
    result = []
    for pkg in raw:
        if pkg not in seen:
            seen.add(pkg)
            result.append(pkg)
    return result


def list_launch_files(launch_dir):
    """Return .py and .xml files from a launch directory."""
    if not os.path.isdir(launch_dir):
        return []
    return [
        os.path.join(launch_dir, f)
        for f in sorted(os.listdir(launch_dir))
        if f.endswith('.py') or f.endswith('.xml')
    ]


def find_pkg_launch_files(pkg_name):
    """Locate the installed launch files for an external package."""
    def _probe(prefix):
        d = os.path.join(prefix, 'share', pkg_name, 'launch')
        files = list_launch_files(d)
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


def find_pkg_in_source_tree(pkg_name, workspace_src_dir):
    """Look for a package's launch/ directory as a sibling in the same src/ folder."""
    candidate = os.path.join(str(workspace_src_dir), pkg_name, 'launch')
    return list_launch_files(candidate)
