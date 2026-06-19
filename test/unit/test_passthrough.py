"""Transparency tests — DendROS must pass every byte ROS prints to the terminal.

Covers: tracebacks, segfaults, signal deaths, empty lines, long lines,
ordering guarantees, lines with special characters, and interleaved error
output alongside normal node lines.
"""
import os
import re
import sys
import pytest

from conftest import (
    run_pipe,
    strip_ansi,
    assert_segment_colored,
    CONFIGS_DIR,
    LINES_DIR,
)

ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def make_prefix(tmp_path, pkg_name, config_name):
    import shutil
    config_dir = tmp_path / 'share' / pkg_name / 'config'
    config_dir.mkdir(parents=True)
    shutil.copy(os.path.join(CONFIGS_DIR, config_name),
                str(config_dir / 'dendROS.yaml'))
    return str(tmp_path)


def no_config_prefix(tmp_path):
    """Return a prefix pointing at an empty dir so no config is found."""
    return str(tmp_path)


PKG = 'passthrough_pkg'


# ── Traceback lines ───────────────────────────────────────────────────────────

class TestTracebackPassthrough:
    TRACEBACK = [
        "Traceback (most recent call last):\n",
        "  File \"/opt/ros/humble/lib/demo.py\", line 42, in callback\n",
        "    self.pub.publish(msg)\n",
        "  File \"/opt/ros/humble/lib/rclpy/publisher.py\", line 96, in publish\n",
        "    self._pub.publish(msg)\n",
        "RuntimeError: publisher handle is invalid\n",
    ]

    def test_traceback_header_unchanged(self, tmp_path):
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', self.TRACEBACK)
        assert 'Traceback (most recent call last):' in stdout

    def test_traceback_file_line_unchanged(self, tmp_path):
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', self.TRACEBACK)
        assert '  File "/opt/ros/humble/lib/demo.py", line 42, in callback' in stdout

    def test_traceback_indented_code_unchanged(self, tmp_path):
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', self.TRACEBACK)
        assert '    self.pub.publish(msg)' in stdout

    def test_exception_line_unchanged(self, tmp_path):
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', self.TRACEBACK)
        assert 'RuntimeError: publisher handle is invalid' in stdout

    def test_traceback_colored_red(self, tmp_path):
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', self.TRACEBACK)
        # Header and exception are bold red; frames are dim red
        assert '\033[31;1m' in stdout   # bold red (header + exception)
        assert '\033[31;2m' in stdout   # dim red (frames)

    def test_traceback_all_lines_present(self, tmp_path):
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', self.TRACEBACK)
        # Strip ANSI to compare text content — coloring may have been added
        assert strip_ansi(stdout) == ''.join(self.TRACEBACK)

    def test_traceback_order_preserved(self, tmp_path):
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', self.TRACEBACK)
        lines = stdout.splitlines()
        tb_idx  = next(i for i, l in enumerate(lines) if 'Traceback' in l)
        err_idx = next(i for i, l in enumerate(lines) if 'RuntimeError' in l)
        assert tb_idx < err_idx


# ── Segfault / signal output ──────────────────────────────────────────────────

class TestSegfaultPassthrough:
    def test_segfault_line_unchanged(self, tmp_path):
        lines = ["Segmentation fault (core dumped)\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == lines[0]

    def test_segfault_no_ansi(self, tmp_path):
        lines = ["Segmentation fault (core dumped)\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert not ANSI_RE.search(stdout)

    def test_signal_death_message_unchanged(self, tmp_path):
        msg = "[ros2run]: Process '[/node]' died with signal 11\n"
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', [msg])
        assert stdout == msg

    def test_signal_death_no_ansi(self, tmp_path):
        msg = "[ros2run]: Process '[/node]' died with signal 11\n"
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', [msg])
        assert not ANSI_RE.search(stdout)


# ── Empty and whitespace lines ────────────────────────────────────────────────

class TestEmptyLinePassthrough:
    def test_empty_line_preserved(self, tmp_path):
        lines = ["line before\n", "\n", "line after\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == ''.join(lines)

    def test_whitespace_only_line_preserved(self, tmp_path):
        lines = ["   \n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == lines[0]

    def test_multiple_empty_lines_preserved(self, tmp_path):
        lines = ["\n", "\n", "\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == ''.join(lines)


# ── Long lines ────────────────────────────────────────────────────────────────

class TestLongLinePassthrough:
    def test_10k_char_line_unchanged(self, tmp_path):
        long_line = 'x' * 10000 + '\n'
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', [long_line])
        assert stdout == long_line

    def test_long_line_no_ansi(self, tmp_path):
        long_line = 'x' * 10000 + '\n'
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', [long_line])
        assert not ANSI_RE.search(stdout)


# ── Special characters and edge-case lines ────────────────────────────────────

class TestSpecialCharPassthrough:
    def test_bracket_only_line_unchanged(self, tmp_path):
        lines = ["[12345]\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == lines[0]

    def test_partial_bracket_unchanged(self, tmp_path):
        lines = ["[unclosed bracket\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == lines[0]

    def test_ansi_like_but_invalid_unchanged(self, tmp_path):
        lines = ["not\\033real escape\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == lines[0]

    def test_colon_in_line_unchanged(self, tmp_path):
        lines = ["key: value with: multiple: colons\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == lines[0]

    def test_line_starting_with_bracket_no_node_format(self, tmp_path):
        # Looks bracket-y but not a valid node line and not a log level
        lines = ["[WARNING] this is a custom warning without node\n"]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert stdout == lines[0]


# ── Ordering guarantee ────────────────────────────────────────────────────────

class TestOrderingGuarantee:
    def test_100_lines_in_order(self, tmp_path):
        lines = [f"line {i:03d}\n" for i in range(100)]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        out_lines = stdout.splitlines()
        for i, line in enumerate(out_lines):
            assert line == f"line {i:03d}", f"Line {i} out of order: {line!r}"

    def test_line_count_preserved(self, tmp_path):
        lines = [f"line {i}\n" for i in range(50)]
        stdout, _, _ = run_pipe(no_config_prefix(tmp_path), 'no_pkg', lines)
        assert len(stdout.splitlines()) == 50


# ── Tracebacks interleaved with node output (with config) ─────────────────────

class TestInterleavedErrorsWithConfig:
    """Colorize node lines but leave tracebacks untouched."""
    PKG = 'interleave_pkg'

    def test_node_line_before_traceback_colored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, 'basic.yaml')
        lines = [
            "[talker-1] [INFO] [1.0] [t]: Normal message\n",
            "Traceback (most recent call last):\n",
            "  File \"foo.py\", line 1, in bar\n",
            "RuntimeError: oops\n",
            "[talker-1] [INFO] [2.0] [t]: Recovered\n",
        ]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        out_lines = stdout.splitlines(keepends=True)
        # First and last lines are node lines — must be colored
        assert_segment_colored(out_lines[0], '[talker-1]', '34')
        assert_segment_colored(out_lines[4], '[talker-1]', '34')

    def test_traceback_in_middle_colored_red(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, 'basic.yaml')
        lines = [
            "[talker-1] [INFO] [1.0] [t]: Normal message\n",
            "Traceback (most recent call last):\n",
            "  File \"foo.py\", line 1, in bar\n",
            "RuntimeError: oops\n",
            "[talker-1] [INFO] [2.0] [t]: Recovered\n",
        ]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        out_lines = stdout.splitlines(keepends=True)
        # Traceback header is bold red
        assert '\033[31;1m' in out_lines[1]
        # Frame line is dim red
        assert '\033[31;2m' in out_lines[2]
        # Exception line is bold red
        assert '\033[31;1m' in out_lines[3]
        # Text content is preserved
        assert 'Traceback' in strip_ansi(out_lines[1])
        assert 'File' in strip_ansi(out_lines[2])
        assert 'RuntimeError' in strip_ansi(out_lines[3])

    def test_all_lines_present_when_interleaved(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, 'basic.yaml')
        lines = [
            "[talker-1] [INFO] [1.0] [t]: msg\n",
            "Traceback (most recent call last):\n",
            "RuntimeError: oops\n",
        ]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert len(stdout.splitlines()) == 3

    def test_segfault_after_node_line_unchanged(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, 'basic.yaml')
        lines = [
            "[talker-1] [INFO] [1.0] [t]: msg\n",
            "Segmentation fault (core dumped)\n",
        ]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        out_lines = stdout.splitlines(keepends=True)
        assert strip_ansi(out_lines[1]) == "Segmentation fault (core dumped)\n"
        assert not ANSI_RE.search(out_lines[1])

    def test_error_output_fixture_line_count(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, 'basic.yaml')
        with open(os.path.join(LINES_DIR, 'error_output.txt')) as f:
            lines = f.readlines()
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert len(stdout.splitlines()) == len(lines)

    def test_error_output_segfault_not_colored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, 'basic.yaml')
        with open(os.path.join(LINES_DIR, 'error_output.txt')) as f:
            lines = f.readlines()
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        for line in stdout.splitlines(keepends=True):
            # Segmentation fault is C-level output — not a Python traceback, not colored
            if 'Segmentation fault' in line:
                assert not ANSI_RE.search(line), f"Segfault should not be colored: {line!r}"
            # Python traceback header is bold red; frame lines are dim red
            if 'Traceback (most recent call last)' in strip_ansi(line):
                assert '\033[31;1m' in line, f"Traceback header should be bold red: {line!r}"
            elif strip_ansi(line).startswith('  File '):
                assert '\033[31;2m' in line, f"Traceback frame should be dim red: {line!r}"
