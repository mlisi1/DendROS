"""Docker integration tests for DendROS.

Builds the Docker image and runs the pipe script inside the container,
feeding fixture lines via stdin.  Verifies colorized output matches expectations.

Requirements:
  - Docker daemon running
  - Build context: repo root (test/Dockerfile uses context '..')

Marked with @pytest.mark.integration — skip with:
    pytest test/unit/               # unit tests only
    pytest -m "not integration"     # skip all integration tests
"""
import os
import re
import subprocess
import sys
import pytest

ANSI_RE = re.compile(r'\033\[([0-9;]*)m')
RESET   = '\033[0m'

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DOCKERFILE  = os.path.join(REPO_ROOT, 'test', 'Dockerfile')
IMAGE_TAG   = 'dendros_test:ci'
PIPE_IN_IMG = '/usr/local/dendROS/dendROS_pipe.py'

# Config/prefix as installed inside the container
IMG_AMENT_PREFIX = '/ros2_ws/install/test_bringup'
IMG_PKG          = 'test_bringup'

# Expected color codes from test/test_bringup/config/dendROS.yaml:
#   talkers:   "@#FF6600"  → bold orange  → "1;38;2;255;102;0"
#   listeners: "bold yellow"             → "33;1"
TALKER_CODE   = '1;38;2;255;102;0'
LISTENER_CODE = '33;1'
TALKER_LABEL  = 'TALK'
LISTENER_LABEL = 'LISTEN'


def docker_available():
    try:
        subprocess.run(['docker', 'info'], capture_output=True, timeout=10, check=True)
        return True
    except Exception:
        return False


def build_image():
    """Build the Docker test image. Returns True on success."""
    result = subprocess.run(
        ['docker', 'build', '-f', DOCKERFILE, '-t', IMAGE_TAG, '.'],
        capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
    )
    return result.returncode == 0, result.stdout + result.stderr


def run_in_docker(lines, env_extra=None, timeout=30):
    """Run dendROS_pipe.py inside the container with given stdin lines.

    Returns (stdout, stderr, returncode).
    """
    env_flags = ['-e', f'AMENT_PREFIX_PATH={IMG_AMENT_PREFIX}',
                 '-e', 'RCUTILS_COLORIZED_OUTPUT=1']
    if env_extra:
        for k, v in env_extra.items():
            env_flags += ['-e', f'{k}={v}']

    cmd = [
        'docker', 'run', '--rm', '-i',
        *env_flags,
        IMAGE_TAG,
        'python3', PIPE_IN_IMG, 'launch', IMG_PKG,
    ]
    stdin_data = ''.join(lines).encode()
    result = subprocess.run(cmd, input=stdin_data, capture_output=True, timeout=timeout)
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
        f"Expected {text!r} colored with {code!r}.\nActual: {s!r}"
    )


def assert_segment_uncolored(s, text):
    for seg_text, seg_code in colored_segments(s):
        if text in seg_text and seg_code is None:
            return
    raise AssertionError(
        f"Expected {text!r} uncolored.\nSegments: {colored_segments(s)!r}\nActual: {s!r}"
    )


def strip_ansi(s):
    return ANSI_RE.sub('', s)


# ── Fixtures / skip markers ───────────────────────────────────────────────────

pytestmark = pytest.mark.integration

@pytest.fixture(scope='session')
def docker_image():
    if not docker_available():
        pytest.skip("Docker daemon not available")
    ok, log = build_image()
    if not ok:
        pytest.fail(f"Docker build failed:\n{log}")
    return IMAGE_TAG


# ── Image build sanity ────────────────────────────────────────────────────────

class TestDockerBuild:
    def test_image_built_successfully(self, docker_image):
        # Fixture handles build — if we get here, build succeeded
        assert docker_image == IMAGE_TAG

    def test_pipe_script_exists_in_image(self, docker_image):
        result = subprocess.run(
            ['docker', 'run', '--rm', IMAGE_TAG, 'test', '-f', PIPE_IN_IMG],
            capture_output=True, timeout=15,
        )
        assert result.returncode == 0, f"Pipe script missing from image at {PIPE_IN_IMG}"

    def test_pyyaml_available_in_image(self, docker_image):
        result = subprocess.run(
            ['docker', 'run', '--rm', IMAGE_TAG, 'python3', '-c', 'import yaml'],
            capture_output=True, timeout=15,
        )
        assert result.returncode == 0, "PyYAML not available in image"

    def test_config_installed_in_image(self, docker_image):
        config_path = f'{IMG_AMENT_PREFIX}/share/{IMG_PKG}/config/dendROS.yaml'
        result = subprocess.run(
            ['docker', 'run', '--rm', IMAGE_TAG, 'test', '-f', config_path],
            capture_output=True, timeout=15,
        )
        assert result.returncode == 0, f"dendROS.yaml missing from {config_path}"


# ── Talker node colorization ──────────────────────────────────────────────────

class TestTalkerColorization:
    TALKER_LINE = "[talker-1] [INFO] [1234.567890] [talker]: Publishing: 'Hello World: 1'\n"

    def test_talker_prefix_colored_exact_code(self, docker_image):
        stdout, _, _ = run_in_docker([self.TALKER_LINE])
        assert_segment_colored(stdout, '[talker-1]', TALKER_CODE)

    def test_talker_badge_present(self, docker_image):
        stdout, _, _ = run_in_docker([self.TALKER_LINE])
        assert f'[{TALKER_LABEL}]' in stdout

    def test_talker_message_uncolored(self, docker_image):
        stdout, _, _ = run_in_docker([self.TALKER_LINE])
        assert_segment_uncolored(stdout, "Publishing: 'Hello World: 1'")

    def test_talker_info_level_uncolored(self, docker_image):
        stdout, _, _ = run_in_docker([self.TALKER_LINE])
        assert_segment_uncolored(stdout, '[INFO]')

    def test_talker_exact_prefix_structure(self, docker_image):
        stdout, _, _ = run_in_docker([self.TALKER_LINE])
        expected_prefix = f'\033[{TALKER_CODE}m[talker-1]\033[0m'
        assert expected_prefix in stdout


# ── Listener node colorization ────────────────────────────────────────────────

class TestListenerColorization:
    LISTENER_LINE = "[listener-1] [INFO] [1234.570000] [listener]: I heard: [Hello World: 1]\n"

    def test_listener_prefix_colored_exact_code(self, docker_image):
        stdout, _, _ = run_in_docker([self.LISTENER_LINE])
        assert_segment_colored(stdout, '[listener-1]', LISTENER_CODE)

    def test_listener_badge_present(self, docker_image):
        stdout, _, _ = run_in_docker([self.LISTENER_LINE])
        assert f'[{LISTENER_LABEL}]' in stdout

    def test_listener_message_uncolored(self, docker_image):
        stdout, _, _ = run_in_docker([self.LISTENER_LINE])
        assert_segment_uncolored(stdout, 'I heard:')

    def test_listener_exact_prefix_structure(self, docker_image):
        stdout, _, _ = run_in_docker([self.LISTENER_LINE])
        expected_prefix = f'\033[{LISTENER_CODE}m[listener-1]\033[0m'
        assert expected_prefix in stdout


# ── Launch framework lines ────────────────────────────────────────────────────

class TestLaunchFrameworkDocker:
    def test_talker_launch_line_colored(self, docker_image):
        line = "[INFO] [talker-1]: process started with pid [12345]\n"
        stdout, _, _ = run_in_docker([line])
        assert_segment_colored(stdout, '[talker-1]', TALKER_CODE)

    def test_launch_level_prefix_uncolored(self, docker_image):
        line = "[INFO] [talker-1]: process started with pid [12345]\n"
        stdout, _, _ = run_in_docker([line])
        assert_segment_uncolored(stdout, '[INFO]')

    def test_listener_launch_line_colored(self, docker_image):
        line = "[INFO] [listener-1]: process started with pid [12346]\n"
        stdout, _, _ = run_in_docker([line])
        assert_segment_colored(stdout, '[listener-1]', LISTENER_CODE)


# ── Unmatched / plain lines ───────────────────────────────────────────────────

class TestPassthroughDocker:
    def test_plain_line_unchanged(self, docker_image):
        line = "Some plain text that is not a ROS node output\n"
        stdout, _, _ = run_in_docker([line])
        assert stdout == line
        assert not ANSI_RE.search(stdout)

    def test_unmatched_node_passes_through(self, docker_image):
        line = "[unknown_node-1] [INFO] [1.0] [u]: message\n"
        stdout, _, _ = run_in_docker([line])
        # No unmatched_color set in test config → passthrough
        assert not ANSI_RE.search(stdout)


# ── Mixed input correctness ───────────────────────────────────────────────────

class TestMixedInputDocker:
    LINES = [
        "[INFO] [talker-1]: process started with pid [12345]\n",
        "[INFO] [listener-1]: process started with pid [12346]\n",
        "[talker-1] [INFO] [1234.567890] [talker]: Publishing: 'Hello World: 1'\n",
        "[listener-1] [INFO] [1234.570000] [listener]: I heard: [Hello World: 1]\n",
        "Some plain line\n",
    ]

    def test_line_count_preserved(self, docker_image):
        stdout, _, _ = run_in_docker(self.LINES)
        assert len(stdout.splitlines()) == len(self.LINES)

    def test_each_line_correctly_handled(self, docker_image):
        stdout, _, _ = run_in_docker(self.LINES)
        out_lines = stdout.splitlines(keepends=True)

        # Line 0: [INFO] [talker-1]: ... → [talker-1] bracket colored
        assert_segment_colored(out_lines[0], '[talker-1]', TALKER_CODE)
        # Line 1: [INFO] [listener-1]: ... → [listener-1] bracket colored
        assert_segment_colored(out_lines[1], '[listener-1]', LISTENER_CODE)
        # Line 2: [talker-1] [INFO] ... → prefix colored
        assert_segment_colored(out_lines[2], '[talker-1]', TALKER_CODE)
        # Line 3: [listener-1] [INFO] ... → prefix colored
        assert_segment_colored(out_lines[3], '[listener-1]', LISTENER_CODE)
        # Line 4: plain → no ANSI
        assert not ANSI_RE.search(out_lines[4])

    def test_exit_code_zero(self, docker_image):
        _, _, rc = run_in_docker(self.LINES)
        assert rc == 0


# ── Debug mode in Docker ──────────────────────────────────────────────────────

class TestDebugModeDocker:
    LINE = "[talker-1] [INFO] [1234.5] [t]: msg\n"

    def test_debug_on_stderr_not_stdout(self, docker_image):
        stdout, stderr, _ = run_in_docker([self.LINE],
                                          env_extra={'DENDROS_DEBUG': '1'})
        assert '[dendROS]' not in stdout
        assert '[dendROS]' in stderr

    def test_stdout_unchanged_in_debug_mode(self, docker_image):
        stdout_debug, _, _  = run_in_docker([self.LINE], env_extra={'DENDROS_DEBUG': '1'})
        stdout_plain, _, _  = run_in_docker([self.LINE])
        assert stdout_debug == stdout_plain
