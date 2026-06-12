"""Shared fixtures and helpers for DendROS unit tests."""
import os
import re
import sys
import subprocess
import textwrap

import pytest
import yaml

# ── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PIPE_PATH   = os.path.join(REPO_ROOT, 'dendROS', 'dendROS_pipe.py')
FIXTURES    = os.path.join(REPO_ROOT, 'test', 'fixtures')
CONFIGS_DIR = os.path.join(FIXTURES, 'configs')
LINES_DIR   = os.path.join(FIXTURES, 'lines')

# ── Import helpers ────────────────────────────────────────────────────────────
# Allow direct function imports in test modules.
sys.path.insert(0, os.path.join(REPO_ROOT, 'dendROS'))

# ── ANSI helpers ─────────────────────────────────────────────────────────────

ANSI_RE = re.compile(r'\033\[([0-9;]*)m')


def strip_ansi(s: str) -> str:
    """Remove all ANSI escape sequences from s."""
    return ANSI_RE.sub('', s)


def ansi_codes(s: str) -> list:
    """Return list of all SGR code strings found in s (in order)."""
    return ANSI_RE.findall(s)


def colored_segments(s: str) -> list:
    """Parse s into (text, active_code_or_None) tuples.

    Tracks the current active color code.  A RESET (code '0' or '') sets it
    back to None.  Text between escapes is associated with the code that
    preceded it.

    Example:
        '\\033[34m[talker-1]\\033[0m rest'
        → [('[talker-1]', '34'), (' rest', None)]
    """
    result = []
    current_code = None
    pos = 0
    for m in ANSI_RE.finditer(s):
        if m.start() > pos:
            text = s[pos:m.start()]
            result.append((text, current_code))
        code = m.group(1)
        current_code = None if code in ('0', '') else code
        pos = m.end()
    if pos < len(s):
        result.append((s[pos:], current_code))
    return result


def assert_segment_colored(s: str, text: str, code: str) -> None:
    """Assert that `text` is wrapped in exactly \\033[{code}m…\\033[0m in s."""
    pattern = rf'\033\[{re.escape(code)}m{re.escape(text)}\033\[0m'
    assert re.search(pattern, s) is not None, (
        f"\nExpected segment {text!r} to be colored with code {code!r}.\n"
        f"Full string repr: {s!r}"
    )


def assert_segment_uncolored(s: str, text: str) -> None:
    """Assert that `text` appears in s in an uncolored (no active code) region."""
    for seg_text, seg_code in colored_segments(s):
        if text in seg_text and seg_code is None:
            return
    raise AssertionError(
        f"\nExpected {text!r} to appear in an uncolored region.\n"
        f"Segments: {colored_segments(s)!r}\n"
        f"Full string repr: {s!r}"
    )


def assert_no_ansi_after(s: str, marker: str) -> None:
    """Assert no ANSI codes appear after the last occurrence of `marker` in s."""
    idx = s.rfind(marker)
    assert idx >= 0, f"Marker {marker!r} not found in {s!r}"
    suffix = s[idx + len(marker):]
    assert not ANSI_RE.search(suffix), (
        f"\nExpected no ANSI codes after {marker!r}.\n"
        f"Suffix repr: {suffix!r}\n"
        f"Full string repr: {s!r}"
    )


# ── Subprocess runner ─────────────────────────────────────────────────────────

def run_pipe(ament_prefix: str, pkg_name: str, lines: list,
             env_extra: dict = None, timeout: int = 10,
             launch_file: str = None) -> tuple:
    """Run dendROS_pipe.py as subprocess and return (stdout, stderr, returncode).

    Args:
        ament_prefix:  value for AMENT_PREFIX_PATH.
        pkg_name:      package name passed as the first positional arg (after 'launch').
        lines:         list of input line strings (newlines included).
        env_extra:     additional env vars to set (or override).
        timeout:       subprocess timeout in seconds.
        launch_file:   optional launch file name passed as second positional arg.
    """
    env = os.environ.copy()
    env['AMENT_PREFIX_PATH'] = ament_prefix
    # Prevent accidental ros2-binary lookup from interfering
    env.pop('ROS_DISTRO', None)
    # Isolate from the user's ~/.config/dendROS/defaults.yaml so global
    # debug/color settings don't leak into tests
    env['HOME'] = ament_prefix
    if env_extra:
        env.update(env_extra)

    cmd = [sys.executable, PIPE_PATH, 'launch', pkg_name]
    if launch_file:
        cmd.append(launch_file)

    stdin_data = ''.join(lines).encode()
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pipe_path():
    return PIPE_PATH


@pytest.fixture
def configs_dir():
    return CONFIGS_DIR


@pytest.fixture
def lines_dir():
    return LINES_DIR


@pytest.fixture
def make_ament_tree(tmp_path):
    """Return a factory that writes a dendROS.yaml into a proper AMENT prefix tree.

    Usage:
        prefix, pkg = make_ament_tree('my_pkg', yaml_dict_or_string)
    Returns (prefix_path_str, pkg_name) ready for run_pipe().
    """
    def _factory(pkg_name: str, config_data):
        config_dir = tmp_path / 'share' / pkg_name / 'config'
        config_dir.mkdir(parents=True)
        config_file = config_dir / 'dendROS.yaml'
        if isinstance(config_data, dict):
            config_file.write_text(yaml.dump(config_data))
        else:
            config_file.write_text(textwrap.dedent(config_data))
        return str(tmp_path), pkg_name
    return _factory


@pytest.fixture
def fixture_config():
    """Return factory that gives the path to a named fixture config."""
    def _get(name: str) -> str:
        path = os.path.join(CONFIGS_DIR, name)
        assert os.path.exists(path), f"Fixture config not found: {path}"
        return path
    return _get


@pytest.fixture
def fixture_lines():
    """Return factory that reads lines from a named fixture file."""
    def _get(name: str) -> list:
        path = os.path.join(LINES_DIR, name)
        with open(path) as f:
            return f.readlines()
    return _get
