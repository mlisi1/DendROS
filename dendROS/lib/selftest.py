"""`dendros test`, pure layer: environment/dependency/config checks and report formatting.

Each check returns a Check(status, label, detail). External probes (imports, PATH lookups,
subprocesses, env) are injectable so test/unit/test_selftest.py runs them without a ROS
install. The curses probe and the actual printing live in dendros_selftest.py.
"""

import os
import re
import shutil
import subprocess
import sys
from typing import NamedTuple

from lib.colors import RESET, _resolve_color

OK, WARN, FAIL, INFO = 'ok', 'warn', 'fail', 'info'

_MARKS = {
    OK:   ('\033[32;1m', '✔'),   # ✔ green
    WARN: ('\033[33;1m', '!'),
    FAIL: ('\033[31;1m', '✘'),   # ✘ red
    INFO: ('\033[2m',    '·'),   # · dim
}

_MIN_PYTHON = (3, 8)
# Numeric settings: (converter the code applies, minimum). `dendros config` saves them as
# strings ('30'), so anything the converter accepts is valid. Every "cycle" field's options
# come from lib.config_fields so the two never drift apart.
_NUMBER_KEYS = {'tui_scrollback_lines': (int, 1), 'crash_alert_interval': (float, 0)}
_COLOR_KEYS = ('unmatched_color',)


class Check(NamedTuple):
    status: str
    label: str
    detail: str


# ── Formatting ───────────────────────────────────────────────────────────────

def format_check(check, label_w=15):
    color, mark = _MARKS[check.status]
    return f'  {color}{mark}{RESET} {check.label:<{label_w}} {check.detail}'


def section_title(title):
    return f'\n\033[1m{title}\033[0m'


def summarize(checks):
    """('3 ok, 1 warning, 0 failed', exit_code) — exit code 1 iff anything failed."""
    n = {s: sum(1 for c in checks if c.status == s) for s in (OK, WARN, FAIL)}
    warn_word = 'warning' if n[WARN] == 1 else 'warnings'
    text = f'{n[OK]} ok, {n[WARN]} {warn_word}, {n[FAIL]} failed'
    return text, (1 if n[FAIL] else 0)


# ── Dependencies ─────────────────────────────────────────────────────────────

def check_python(version_info=sys.version_info):
    v = '.'.join(str(x) for x in version_info[:3])
    if tuple(version_info[:2]) < _MIN_PYTHON:
        return Check(FAIL, 'Python', f'{v} (DendROS needs 3.8 or newer)')
    return Check(OK, 'Python', v)


def check_module(label, module, required, hint, version_attr='__version__', importer=None):
    """Import `module`; required → FAIL when missing, optional → WARN."""
    importer = importer or __import__
    try:
        mod = importer(module)
    except Exception:
        return Check(FAIL if required else WARN, label, f'not importable ({hint})')
    version = getattr(mod, version_attr, None)
    return Check(OK, label, str(version) if version else 'importable')


def check_curses(importer=None):
    importer = importer or __import__
    try:
        mod = importer('curses')
    except Exception:
        return Check(WARN, 'curses', 'not importable (ros2 launch falls back to classic mode)')
    nc = getattr(mod, 'ncurses_version', None)
    return Check(OK, 'curses', f'ncurses {nc.major}.{nc.minor}' if nc else 'importable')


def check_ros2(env=None, which=shutil.which):
    env = os.environ if env is None else env
    path = env.get('DENDROS_ROS2_BIN') or which('ros2')
    distro = env.get('ROS_DISTRO')
    if not path:
        if distro and os.path.isfile(f'/opt/ros/{distro}/bin/ros2'):
            path = f'/opt/ros/{distro}/bin/ros2'
        else:
            return Check(FAIL, 'ros2', 'not found on PATH (source /opt/ros/<distro>/setup.bash)')
    return Check(OK, 'ros2', f'{path}  (ROS_DISTRO={distro or "unset"})')


def check_rclpy(run=subprocess.run):
    """rclpy is imported in a subprocess: a broken ROS env can print or hang on import."""
    try:
        r = run([sys.executable, '-c', 'import rclpy'], capture_output=True, timeout=10)
        ok = r.returncode == 0
    except Exception:
        ok = False
    if ok:
        return Check(OK, 'rclpy', 'importable')
    return Check(WARN, 'rclpy', 'not importable (ros2 node info / topic list use slower CLI fallbacks)')


def check_clipboard(which=shutil.which):
    from lib.tui_clipboard import find_clipboard_tool
    tool = find_clipboard_tool(which)
    if tool:
        return Check(OK, 'clipboard', f'{tool[0]} (+ OSC 52)')
    return Check(WARN, 'clipboard', 'no xclip/xsel/wl-copy: TUI copy relies on OSC 52 only')


def dependency_checks():
    return [
        check_python(),
        check_module('PyYAML', 'yaml', True, 'pip3 install pyyaml'),
        check_curses(),
        check_ros2(),
        check_rclpy(),
        check_clipboard(),
    ]


# ── Shell + config ───────────────────────────────────────────────────────────

def check_wrapper(env=None):
    """dendROS.sh passes `type -t ros2` as DENDROS_ROS2_TYPE; absent = run outside dendros()."""
    env = os.environ if env is None else env
    kind = env.get('DENDROS_ROS2_TYPE')
    if kind is None:
        return Check(INFO, 'ros2 wrapper', 'not checked (run through the dendros shell command)')
    if kind == 'function':
        return Check(OK, 'ros2 wrapper', 'ros2 is the DendROS shell function')
    return Check(FAIL, 'ros2 wrapper',
                 f'ros2 is a {kind or "missing command"}, not the DendROS function '
                 '(another alias or function shadows it after dendROS.sh is sourced)')


def check_enabled(env=None, flag_set=None):
    env = os.environ if env is None else env
    if flag_set is None:
        from lib.global_config import is_disable_flag_set
        flag_set = is_disable_flag_set()
    local = env.get('DENDROS_DISABLE', '') not in ('', '0')
    if flag_set:
        return Check(WARN, 'status', 'disabled system-wide (dendros enable to turn it back on)')
    if local:
        return Check(WARN, 'status', 'disabled in this shell (DENDROS_DISABLE is set)')
    return Check(OK, 'status', 'enabled')


def check_config_dir(path):
    shown = _home_relative(path)
    if os.path.isdir(path):
        if os.access(path, os.W_OK):
            return Check(OK, 'config dir', f'{shown} (writable)')
        return Check(FAIL, 'config dir', f'{shown} is not writable (node colors, disable, reopen break)')
    parent = os.path.dirname(path)
    while parent and not os.path.isdir(parent):
        parent = os.path.dirname(parent)
    if parent and os.access(parent, os.W_OK):
        return Check(OK, 'config dir', f'{shown} (created on first launch)')
    return Check(FAIL, 'config dir', f'{shown} cannot be created')


def validate_global_config(data):
    """Problems in a raw defaults.yaml mapping, as strings. Unknown keys are reported too:
    load_global_config() silently ignores them, so a typo there is otherwise invisible."""
    from lib.config_fields import _FIELDS
    from lib.global_config import DEFAULTS

    if not isinstance(data, dict):
        return ['top level is not a mapping']
    problems = []
    cycle_opts = {f.key: f.opts for f in _FIELDS if f.kind == 'cycle'}
    for key, value in data.items():
        if key not in DEFAULTS:
            problems.append(f'unknown key {key!r}')
        elif key in cycle_opts and value not in cycle_opts[key] and not (
                value is None and None in cycle_opts[key]):
            # init_color's "null" option is spelled as a string in config_fields.
            if key == 'init_color' and value is None:
                continue
            opts = '|'.join(str(o).lower() if isinstance(o, bool) else str(o)
                            for o in cycle_opts[key])
            problems.append(f'{key}: {value!r} (expected {opts})')
        elif key in _NUMBER_KEYS and not _number_ok(value, *_NUMBER_KEYS[key]):
            kind = 'an integer' if _NUMBER_KEYS[key][0] is int else 'a number'
            problems.append(f'{key}: {value!r} (expected {kind} >= {_NUMBER_KEYS[key][1]})')
        elif key in _COLOR_KEYS and value is not None and not is_valid_color(value):
            problems.append(f'{key}: {value!r} is not a color')
    return problems


def _number_ok(value, convert, minimum):
    if isinstance(value, bool):
        return False
    try:
        return convert(value) >= minimum
    except (TypeError, ValueError):
        return False


def is_valid_color(value):
    """_resolve_color() passes unknown words through verbatim; a real result is SGR digits."""
    return bool(re.fullmatch(r'[0-9;]+', _resolve_color(value)))


def check_global_config(path, yaml_module):
    shown = _home_relative(path)
    if not os.path.isfile(path):
        return [Check(OK, 'global config', f'{shown} not created yet: stock defaults')]
    if yaml_module is None:
        return [Check(FAIL, 'global config', 'cannot be read without PyYAML')]
    try:
        with open(path) as f:
            data = yaml_module.safe_load(f) or {}
    except Exception as e:
        first = str(e).splitlines()[0] if str(e) else type(e).__name__
        return [Check(FAIL, 'global config', f'{shown}: YAML error, every setting falls back '
                                             f'to its default ({first})')]
    problems = validate_global_config(data)
    if not problems:
        return [Check(OK, 'global config', shown)]
    checks = [Check(WARN, 'global config', f'{shown}: {len(problems)} problem(s)')]
    checks += [Check(WARN, '', p) for p in problems]
    return checks


def check_launch_mode(cfg, stdout_tty):
    mode = cfg.get('launch_mode', 'tui')
    if mode != 'tui':
        return Check(OK, 'launch mode', f'{mode}')
    if not stdout_tty:
        return Check(INFO, 'launch mode', 'tui (this output is not a terminal, so a launch '
                                          'here would fall back to classic)')
    return Check(OK, 'launch mode', 'tui')


def find_package_configs(env=None):
    """[(package, path)] for every installed package shipping config/dendROS.yaml."""
    env = os.environ if env is None else env
    found, seen = [], set()
    for prefix in env.get('AMENT_PREFIX_PATH', '').split(':'):
        share = os.path.join(prefix, 'share') if prefix else ''
        if not share or not os.path.isdir(share):
            continue
        try:
            names = sorted(os.listdir(share))
        except OSError:
            continue
        for pkg in names:
            path = os.path.join(share, pkg, 'config', 'dendROS.yaml')
            if pkg not in seen and os.path.isfile(path):
                seen.add(pkg)
                found.append((pkg, path))
    return found


def check_package_configs(configs, loader):
    """One summary line, plus a FAIL per config that doesn't load (the pipe would then run
    that package in passthrough, only printing the error to stderr)."""
    if not configs:
        return [Check(INFO, 'package configs', 'none installed (dendros init creates one)')]
    broken = []
    for pkg, path in configs:
        try:
            loader(path)
        except Exception as e:
            first = str(e).splitlines()[0] if str(e) else type(e).__name__
            broken.append(Check(FAIL, '', f'{pkg}: {first}'))
    names = ', '.join(pkg for pkg, _ in configs[:6]) + (' ...' if len(configs) > 6 else '')
    head = Check(FAIL if broken else OK, 'package configs',
                 f'{len(configs)} found: {names}')
    return [head] + broken


# ── Terminal ─────────────────────────────────────────────────────────────────

def check_term(env=None):
    env = os.environ if env is None else env
    term = env.get('TERM', '')
    colorterm = env.get('COLORTERM', '')
    detail = f'TERM={term or "unset"}' + (f', COLORTERM={colorterm}' if colorterm else '')
    if not term or term == 'dumb':
        return Check(WARN, 'terminal', f'{detail}: no TUI, no colors')
    return Check(OK, 'terminal', detail)


def truecolor_check(env=None):
    env = os.environ if env is None else env
    if env.get('COLORTERM', '').lower() in ('truecolor', '24bit'):
        return Check(OK, '24-bit color', 'advertised (COLORTERM); hex and extended colors exact')
    return Check(INFO, '24-bit color', 'not advertised: check the gradient below; if it bands, '
                                       'hex/extended colors are approximated')


def curses_probe_checks(info):
    """Turn dendros_selftest's curses probe result dict into checks."""
    if info.get('skipped'):
        return [Check(INFO, 'TUI', info['skipped'])]
    if info.get('error'):
        return [Check(FAIL, 'TUI', f'failed to open: {info["error"]} '
                                   '(ros2 launch would fall back to classic)')]
    n = info['colors']
    if n >= 256:
        colors = Check(OK, 'TUI colors', f'{n} colors, {info["pairs"]} color pairs')
    elif n >= 8:
        colors = Check(WARN, 'TUI colors', f'only {n} colors: node colors are mapped to the '
                                           'nearest base color (try TERM=xterm-256color)')
    else:
        colors = Check(WARN, 'TUI colors', 'no color support: TUI is monochrome')
    if info['console'] == 'exact':
        brand = Check(OK, 'TUI palette', 'terminal reports palette changes: console bar in exact brand colors')
    elif info['console'] == 'stock':
        brand = Check(INFO, 'TUI palette', 'fixed: console bar uses the nearest stock blue/orange')
    else:
        brand = Check(INFO, 'TUI palette', 'console bar uses base blue/yellow')
    return [Check(OK, 'TUI', f'opened and closed cleanly ({info["cols"]}x{info["rows"]})'),
            colors, brand]


def _home_relative(path):
    home = os.path.expanduser('~')
    return '~' + path[len(home):] if home and path.startswith(home + os.sep) else path
