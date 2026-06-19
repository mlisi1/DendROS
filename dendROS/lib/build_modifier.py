"""Build system file patching for dendros init (CMake, setup.py, setup.cfg)."""

import re

_CMAKE_INSTALL_SNIPPET = (
    '\ninstall(DIRECTORY config/\n'
    '  DESTINATION share/${PROJECT_NAME}\n'
    ')\n'
)


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
