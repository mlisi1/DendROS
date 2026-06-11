"""Host integration tests for DendROS.

Runs the pipe script directly on the host against the pre-built test_bringup
install tree (test/install/test_bringup).  Does NOT require ROS — only uses
AMENT_PREFIX_PATH to find the config.

Marked with @pytest.mark.integration.
"""
import os
import re
import sys
import subprocess
import pytest

ANSI_RE = re.compile(r'\033\[([0-9;]*)m')
RESET   = '\033[0m'

REPO_ROOT    = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PIPE_PATH    = os.path.join(REPO_ROOT, 'dendROS', 'dendROS_pipe.py')
INSTALL_TREE = os.path.join(REPO_ROOT, 'test', 'install', 'test_bringup')
PKG_NAME     = 'test_bringup'
LINES_DIR    = os.path.join(REPO_ROOT, 'test', 'fixtures', 'lines')

# Expected color codes from test/test_bringup/config/dendROS.yaml
TALKER_CODE   = '1;38;2;255;102;0'
LISTENER_CODE = '33;1'
TALKER_LABEL  = 'TALK'
LISTENER_LABEL = 'LISTEN'


def install_tree_present():
    config = os.path.join(INSTALL_TREE, 'share', PKG_NAME, 'config', 'dendROS.yaml')
    return os.path.isfile(config)


def run_host_pipe(lines, env_extra=None, timeout=15):
    env = os.environ.copy()
    env['AMENT_PREFIX_PATH'] = INSTALL_TREE
    env.pop('ROS_DISTRO', None)
    if env_extra:
        env.update(env_extra)
    stdin_data = ''.join(lines).encode()
    result = subprocess.run(
        [sys.executable, PIPE_PATH, 'launch', PKG_NAME],
        input=stdin_data, capture_output=True, env=env, timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


def colored_segments(s):
    result, current_code, pos = [], None, 0
    for m in ANSI_RE.finditer(s):
        if m.start() > pos:
            result.append((s[pos:m.start()], current_code))
        code = m.group(1)
        current_code = None if code in ('0', '') else code
        pos = m.end()
    if pos < len(s):
        result.append((s[pos:], current_code))
    return result


def assert_segment_colored(s, text, code):
    pattern = rf'\033\[{re.escape(code)}m{re.escape(text)}\033\[0m'
    assert re.search(pattern, s) is not None, (
        f"\nExpected {text!r} colored with {code!r}.\nActual: {s!r}"
    )


def assert_segment_uncolored(s, text):
    for seg_text, seg_code in colored_segments(s):
        if text in seg_text and seg_code is None:
            return
    raise AssertionError(
        f"\nExpected {text!r} uncolored.\nSegments: {colored_segments(s)!r}\nActual: {s!r}"
    )


def strip_ansi(s):
    return ANSI_RE.sub('', s)


def fixture_lines(name):
    with open(os.path.join(LINES_DIR, name)) as f:
        return f.readlines()


pytestmark = pytest.mark.integration

skip_if_no_install = pytest.mark.skipif(
    not install_tree_present(),
    reason=f"test_bringup install tree not found at {INSTALL_TREE}"
)


# ── Config discovery ──────────────────────────────────────────────────────────

@skip_if_no_install
class TestConfigDiscovery:
    def test_config_found_via_ament_prefix_path(self):
        lines = ["[talker-1] [INFO] [1.0] [t]: msg\n"]
        stdout, _, _ = run_host_pipe(lines)
        # If config is found, ANSI codes will be present
        assert ANSI_RE.search(stdout), "No ANSI codes: config may not have been found"

    def test_config_not_found_with_wrong_prefix(self, tmp_path):
        env = os.environ.copy()
        env['AMENT_PREFIX_PATH'] = str(tmp_path)
        env.pop('ROS_DISTRO', None)
        lines = ["[talker-1] [INFO] [1.0] [t]: msg\n"]
        result = subprocess.run(
            [sys.executable, PIPE_PATH, 'launch', PKG_NAME],
            input=''.join(lines).encode(), capture_output=True, env=env, timeout=10,
        )
        stdout = result.stdout.decode()
        assert not ANSI_RE.search(stdout), "Should be passthrough with wrong prefix"


# ── Talker colorization (host) ────────────────────────────────────────────────

@skip_if_no_install
class TestTalkerHost:
    LINE = "[talker-1] [INFO] [1234.567890] [talker]: Publishing: 'Hello World: 1'\n"

    def test_prefix_colored_exact(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert_segment_colored(stdout, '[talker-1]', TALKER_CODE)

    def test_badge_present(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert f'[{TALKER_LABEL}]' in stdout

    def test_message_uncolored(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert_segment_uncolored(stdout, "Publishing: 'Hello World: 1'")

    def test_info_level_uncolored(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert_segment_uncolored(stdout, '[INFO]')

    def test_timestamp_uncolored(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert_segment_uncolored(stdout, '[1234.567890]')

    def test_exact_prefix_structure(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        expected = f'\033[{TALKER_CODE}m[talker-1]\033[0m'
        assert expected in stdout


# ── Listener colorization (host) ──────────────────────────────────────────────

@skip_if_no_install
class TestListenerHost:
    LINE = "[listener-1] [INFO] [1234.570000] [listener]: I heard: [Hello World: 1]\n"

    def test_prefix_colored_exact(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert_segment_colored(stdout, '[listener-1]', LISTENER_CODE)

    def test_badge_present(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert f'[{LISTENER_LABEL}]' in stdout

    def test_message_uncolored(self):
        stdout, _, _ = run_host_pipe([self.LINE])
        assert_segment_uncolored(stdout, 'I heard:')


# ── Launch framework lines (host) ─────────────────────────────────────────────

@skip_if_no_install
class TestLaunchFrameworkHost:
    def test_talker_bracket_colored(self):
        line = "[INFO] [talker-1]: process started with pid [12345]\n"
        stdout, _, _ = run_host_pipe([line])
        assert_segment_colored(stdout, '[talker-1]', TALKER_CODE)

    def test_level_prefix_uncolored(self):
        line = "[INFO] [talker-1]: process started with pid [12345]\n"
        stdout, _, _ = run_host_pipe([line])
        assert_segment_uncolored(stdout, '[INFO]')

    def test_listener_bracket_colored(self):
        line = "[INFO] [listener-1]: process started with pid [12346]\n"
        stdout, _, _ = run_host_pipe([line])
        assert_segment_colored(stdout, '[listener-1]', LISTENER_CODE)

    def test_warn_level_preserved(self):
        line = "[WARN] [talker-1]: some warning\n"
        stdout, _, _ = run_host_pipe([line])
        assert stdout.startswith('[WARN] ')
        assert_segment_colored(stdout, '[talker-1]', TALKER_CODE)


# ── Mixed input file (host) ───────────────────────────────────────────────────

@skip_if_no_install
class TestMixedInputHost:
    def test_node_output_lines_colored(self):
        lines = fixture_lines('node_output.txt')
        stdout, _, _ = run_host_pipe(lines)
        out_lines = stdout.splitlines(keepends=True)
        for line in out_lines:
            plain = strip_ansi(line)
            if plain.startswith('[talker-'):
                assert ANSI_RE.search(line), f"talker line should be colored: {line!r}"
            elif plain.startswith('[listener-'):
                assert ANSI_RE.search(line), f"listener line should be colored: {line!r}"

    def test_launch_framework_lines_colored(self):
        lines = fixture_lines('launch_framework.txt')
        stdout, _, _ = run_host_pipe(lines)
        out_lines = stdout.splitlines(keepends=True)
        for line in out_lines:
            plain = strip_ansi(line)
            # Any line with [talker-N] or [listener-N] should have color on the bracket
            if '[talker-' in plain or '[listener-' in plain:
                assert ANSI_RE.search(line), f"launch line should be colored: {line!r}"

    def test_line_count_preserved(self):
        lines = fixture_lines('mixed.txt')
        stdout, _, _ = run_host_pipe(lines)
        assert len(stdout.splitlines()) == len(lines)

    def test_plain_lines_unchanged(self):
        lines = fixture_lines('mixed.txt')
        stdout, _, _ = run_host_pipe(lines)
        out_lines = stdout.splitlines(keepends=True)
        in_lines  = lines
        for in_line, out_line in zip(in_lines, out_lines):
            if not in_line.startswith('['):
                # Plain line should be identical
                assert out_line == in_line, (
                    f"Plain line should be unchanged.\n"
                    f"Input:  {in_line!r}\n"
                    f"Output: {out_line!r}"
                )

    def test_exit_code_zero(self):
        _, _, rc = run_host_pipe(fixture_lines('mixed.txt'))
        assert rc == 0


# ── Unmatched nodes (host) ────────────────────────────────────────────────────

@skip_if_no_install
class TestUnmatchedHost:
    def test_unmatched_node_passes_through(self):
        # test_bringup config has no unmatched_color → passthrough
        lines = fixture_lines('unmatched.txt')
        stdout, _, _ = run_host_pipe(lines)
        assert not ANSI_RE.search(stdout), (
            "Unmatched nodes should produce no ANSI codes with null unmatched_color"
        )

    def test_unmatched_plain_text_preserved(self):
        lines = fixture_lines('unmatched.txt')
        stdout, _, _ = run_host_pipe(lines)
        assert strip_ansi(stdout) == strip_ansi(''.join(lines))


# ── Debug mode (host) ─────────────────────────────────────────────────────────

@skip_if_no_install
class TestDebugHost:
    LINE = "[talker-1] [INFO] [1.0] [t]: msg\n"

    def test_debug_on_stderr_not_stdout(self):
        stdout, stderr, _ = run_host_pipe([self.LINE],
                                          env_extra={'DENDROS_DEBUG': '1'})
        assert '[dendROS]' not in stdout
        assert '[dendROS]' in stderr

    def test_config_path_in_debug(self):
        _, stderr, _ = run_host_pipe([self.LINE], env_extra={'DENDROS_DEBUG': '1'})
        assert 'dendROS.yaml' in strip_ansi(stderr)

    def test_stdout_identical_debug_vs_nodebug(self):
        stdout_debug, _, _ = run_host_pipe([self.LINE], env_extra={'DENDROS_DEBUG': '1'})
        stdout_plain, _, _ = run_host_pipe([self.LINE])
        assert stdout_debug == stdout_plain
