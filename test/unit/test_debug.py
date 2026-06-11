"""Tests for DENDROS_DEBUG=1 stderr output.

Verifies that debug information is printed to stderr only, not stdout,
and that the output contains the expected structured information.
"""
import os
import re
import sys
import pytest

from conftest import (
    run_pipe,
    strip_ansi,
    CONFIGS_DIR,
    LINES_DIR,
)

ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def make_prefix(tmp_path, pkg_name, config_name):
    import shutil
    config_dir = tmp_path / 'share' / pkg_name / 'config'
    config_dir.mkdir(parents=True)
    src = os.path.join(CONFIGS_DIR, config_name)
    shutil.copy(src, str(config_dir / 'dendROS.yaml'))
    return str(tmp_path)


def fixture_lines(name):
    with open(os.path.join(LINES_DIR, name)) as f:
        return f.readlines()


PKG = 'debug_test_pkg'
INPUT_LINE = "[talker-1] [INFO] [1234.5] [/talker]: Hello\n"


# ── Debug output appears on stderr only ───────────────────────────────────────

class TestDebugGoesToStderr:
    def test_stdout_unchanged_in_debug_mode(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        stdout_debug, _, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                      env_extra={'DENDROS_DEBUG': '1'})
        stdout_nodebug, _, _ = run_pipe(prefix, PKG, [INPUT_LINE])
        assert stdout_debug == stdout_nodebug

    def test_no_debug_lines_on_stdout(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        stdout, _, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        assert '[dendROS]' not in stdout

    def test_debug_lines_appear_on_stderr(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        assert '[dendROS]' in stderr

    def test_no_debug_output_when_not_set(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE])
        assert strip_ansi(stderr).strip() == ''

    def test_debug_zero_suppresses_output(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '0'})
        assert '[dendROS]' not in stderr


# ── Debug output content ──────────────────────────────────────────────────────

class TestDebugContent:
    def test_config_path_reported(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert 'config:' in plain_stderr

    def test_package_name_reported(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert PKG in plain_stderr

    def test_color_mode_reported(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert 'mode=' in plain_stderr

    def test_show_tag_reported(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert 'show_tag=' in plain_stderr

    def test_unmatched_color_reported(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert 'unmatched=' in plain_stderr

    def test_group_count_reported(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        # Should mention the number of groups
        assert 'group' in plain_stderr

    def test_node_names_listed(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert 'talker' in plain_stderr

    def test_colored_block_in_stderr(self, tmp_path):
        # Debug output uses a colored █ block — raw ANSI codes present in stderr
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        assert ANSI_RE.search(stderr)
        assert '█' in stderr

    def test_config_path_value_is_real_path(self, tmp_path):
        prefix = make_prefix(tmp_path, PKG, 'basic.yaml')
        _, stderr, _ = run_pipe(prefix, PKG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        # The config path line should contain 'dendROS.yaml'
        assert 'dendROS.yaml' in plain_stderr


# ── Debug with multi-group config ─────────────────────────────────────────────

class TestDebugMultiGroup:
    PKG_MG = 'debug_mg_pkg'

    def test_all_group_labels_in_debug(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG_MG, 'multi_group.yaml')
        _, stderr, _ = run_pipe(prefix, self.PKG_MG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        for label in ('NAV', 'LOC', 'HW'):
            assert label in plain_stderr, f"Label {label!r} missing from debug output"

    def test_all_node_names_in_debug(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG_MG, 'multi_group.yaml')
        _, stderr, _ = run_pipe(prefix, self.PKG_MG, [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        for node in ('nav2_controller', 'slam_toolbox', 'lidar_driver'):
            assert node in plain_stderr, f"Node {node!r} missing from debug output"


# ── Debug when no config found ────────────────────────────────────────────────

class TestDebugNoConfig:
    def test_passthrough_mode_message(self, tmp_path):
        # Empty prefix → no config found
        _, stderr, _ = run_pipe(str(tmp_path), 'nonexistent_pkg', [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert 'passthrough' in plain_stderr

    def test_package_name_still_reported(self, tmp_path):
        _, stderr, _ = run_pipe(str(tmp_path), 'nonexistent_pkg', [INPUT_LINE],
                                env_extra={'DENDROS_DEBUG': '1'})
        plain_stderr = strip_ansi(stderr)
        assert 'nonexistent_pkg' in plain_stderr

    def test_stdout_still_correct_passthrough(self, tmp_path):
        lines = [INPUT_LINE, "plain line\n"]
        stdout, _, _ = run_pipe(str(tmp_path), 'nonexistent_pkg', lines,
                                env_extra={'DENDROS_DEBUG': '1'})
        assert stdout == ''.join(lines)
