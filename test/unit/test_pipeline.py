"""End-to-end pipeline tests — run the full pipe script as subprocess.

Verifies that stdin lines come out correctly colorized (or passed through),
using AMENT_PREFIX_PATH to make the fixture configs discoverable.
"""
import os
import re
import sys
import pytest
import yaml

from conftest import (
    run_pipe,
    colored_segments,
    assert_segment_colored,
    assert_segment_uncolored,
    strip_ansi,
    ANSI_RE,
    CONFIGS_DIR,
    LINES_DIR,
)

RESET = '\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_prefix(tmp_path, pkg_name, config_yaml_path):
    """Copy a fixture config into a proper AMENT prefix tree under tmp_path."""
    config_dir = tmp_path / 'share' / pkg_name / 'config'
    config_dir.mkdir(parents=True)
    dest = config_dir / 'dendROS.yaml'
    dest.write_bytes(open(config_yaml_path, 'rb').read())
    return str(tmp_path)


def fixture_config(name):
    return os.path.join(CONFIGS_DIR, name)


def fixture_lines(name):
    with open(os.path.join(LINES_DIR, name)) as f:
        return f.readlines()


# ── basic tag_only ────────────────────────────────────────────────────────────

class TestBasicTagOnly:
    PKG = 'test_pkg'

    def test_node_prefix_colored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, rc = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[talker-1]', '34')

    def test_message_text_uncolored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_uncolored(stdout, 'Hello')

    def test_badge_inserted(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[TALK]' in stdout

    def test_launch_framework_node_bracket_colored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[INFO] [talker-1]: process started with pid [1234]\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[talker-1]', '34')

    def test_launch_framework_level_prefix_uncolored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[INFO] [talker-1]: process started with pid [1234]\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_uncolored(stdout, '[INFO]')

    def test_plain_line_passes_through(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["Some plain text line\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert stdout == "Some plain text line\n"
        assert not ANSI_RE.search(stdout)

    def test_exit_code_zero(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        _, _, rc = run_pipe(prefix, self.PKG, ["[talker-1] [INFO] [1.0] [t]: msg\n"])
        assert rc == 0

    def test_multiline_correct_per_line(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = fixture_lines('node_output.txt')
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        out_lines = stdout.splitlines(keepends=True)
        # All [talker-N] lines must have their prefix colored
        for line in out_lines:
            plain = strip_ansi(line)
            if plain.startswith('[talker-'):
                bracket = plain.split(']')[0] + ']'   # e.g. '[talker-1]'
                assert_segment_colored(line, bracket, '34')

    def test_badge_before_message_in_output(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        badge_pos = stdout.find('[TALK]')
        msg_pos   = stdout.find('Hello')
        assert badge_pos < msg_pos


# ── full_line mode ────────────────────────────────────────────────────────────

class TestFullLineMode:
    PKG = 'test_pkg_fl'

    def test_entire_line_colored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('full_line_mode.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello world\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert stdout.startswith('\033[34m')
        assert RESET in stdout

    def test_no_uncolored_text_segments(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('full_line_mode.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello world\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        segs = colored_segments(stdout.rstrip('\n'))
        uncolored = [t for t, c in segs if c is None and t.strip()]
        assert not uncolored

    def test_badge_in_colored_region(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('full_line_mode.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello world\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[TALK]' in strip_ansi(stdout)


# ── no_tag mode ───────────────────────────────────────────────────────────────

class TestNoTag:
    PKG = 'test_pkg_notag'

    def test_no_badge_in_output(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('no_tag.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[TALK]' not in stdout

    def test_prefix_still_colored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('no_tag.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[talker-1]', '34')


# ── unmatched nodes ───────────────────────────────────────────────────────────

class TestUnmatchedNodes:
    PKG = 'test_pkg_um'

    def test_unmatched_no_unmatched_color_passes_through(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[unknown_node-1] [INFO] [1234.5] [u]: message\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        # Should pass through unchanged (no ANSI codes)
        assert not ANSI_RE.search(stdout)
        assert strip_ansi(stdout) == strip_ansi(lines[0])

    def test_unmatched_with_unmatched_color_colored(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('unmatched_color.yaml'))
        lines = ["[unknown_node-1] [INFO] [1234.5] [u]: message\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        # Should be colored with the unmatched_color (red = 31)
        assert ANSI_RE.search(stdout)
        assert_segment_colored(stdout, '[unknown_node-1]', '31')

    def test_known_node_with_unmatched_config_still_correct(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('unmatched_color.yaml'))
        lines = ["[known_node-1] [INFO] [1234.5] [k]: message\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[known_node-1]', '34')


# ── passthrough (no config) ───────────────────────────────────────────────────

class TestNoConfig:
    def test_all_lines_passed_through_unchanged(self, tmp_path):
        # Point AMENT_PREFIX_PATH at an empty dir — no config will be found
        empty_prefix = str(tmp_path)
        lines = [
            "[talker-1] [INFO] [1234.5] [/talker]: Hello\n",
            "[INFO] [listener-1]: process started\n",
            "plain text line\n",
        ]
        stdout, _, rc = run_pipe(empty_prefix, 'nonexistent_pkg', lines)
        assert stdout == ''.join(lines)
        assert rc == 0

    def test_no_ansi_codes_without_config(self, tmp_path):
        lines = ["[talker-1] [INFO] [1234.5] [t]: msg\n"]
        stdout, _, _ = run_pipe(str(tmp_path), 'nonexistent_pkg', lines)
        assert not ANSI_RE.search(stdout)


# ── multi_group config ────────────────────────────────────────────────────────

class TestMultiGroup:
    PKG = 'test_pkg_mg'

    def test_nav_nodes_colored_bold_green(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('multi_group.yaml'))
        from dendROS_pipe import _resolve_color
        nav_code = _resolve_color('bold green')
        lines = [
            "[nav2_controller-1] [INFO] [1.0] [n]: Planning\n",
            "[nav2_planner-1] [INFO] [1.0] [n]: Computing path\n",
        ]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        out_lines = stdout.splitlines(keepends=True)
        assert_segment_colored(out_lines[0], '[nav2_controller-1]', nav_code)
        assert_segment_colored(out_lines[1], '[nav2_planner-1]', nav_code)

    def test_loc_nodes_colored_bold_blue(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('multi_group.yaml'))
        from dendROS_pipe import _resolve_color
        loc_code = _resolve_color('bold blue')
        lines = ["[slam_toolbox-1] [INFO] [1.0] [s]: Scanning\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[slam_toolbox-1]', loc_code)

    def test_different_groups_get_different_colors(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('multi_group.yaml'))
        lines = [
            "[nav2_controller-1] [INFO] [1.0] [n]: msg\n",
            "[slam_toolbox-1] [INFO] [1.0] [s]: msg\n",
        ]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        out_lines = stdout.splitlines(keepends=True)
        nav_codes  = ANSI_RE.findall(out_lines[0])
        loc_codes  = ANSI_RE.findall(out_lines[1])
        active_nav = [c for c in nav_codes if c not in ('0', '')]
        active_loc = [c for c in loc_codes if c not in ('0', '')]
        assert active_nav != active_loc


# ── hex colors via pipeline ───────────────────────────────────────────────────

class TestHexColorsPipeline:
    PKG = 'test_pkg_hex'

    def test_plain_hex_applied(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('hex_colors.yaml'))
        lines = ["[node_a-1] [INFO] [1.0] [n]: msg\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[node_a-1]', '38;2;255;102;0')

    def test_at_bold_hex_applied(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('hex_colors.yaml'))
        lines = ["[node_b-1] [INFO] [1.0] [n]: msg\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[node_b-1]', '1;38;2;0;170;255')


# ── namespace resolution via pipeline ────────────────────────────────────────

class TestNamespacePipeline:
    PKG = 'test_pkg_ns'

    def test_basename_match_for_namespaced_node(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        # Config has 'talker'; node appears as /robot/talker in output
        lines = ["[/robot/talker-1] [INFO] [1.0] [t]: msg\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        # Should match via basename fallback
        from dendROS_pipe import _resolve_color
        assert ANSI_RE.search(stdout)

    def test_full_namespace_match(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('namespace.yaml'))
        lines = ["[/robot/talker-1] [INFO] [1.0] [t]: msg\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[/robot/talker-1]', '35')


# ── mixed input file ──────────────────────────────────────────────────────────

class TestMixedInput:
    PKG = 'test_pkg_mix'

    def test_mixed_file_correct_coloring(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = fixture_lines('mixed.txt')
        stdout, _, rc = run_pipe(prefix, self.PKG, lines)
        out_lines = stdout.splitlines(keepends=True)
        assert rc == 0
        for line in out_lines:
            plain = strip_ansi(line)
            if plain.startswith('[talker-'):
                assert ANSI_RE.search(line), f"talker line should be colored: {line!r}"
            elif plain.startswith('Some plain text'):
                assert not ANSI_RE.search(line), f"plain line should not be colored: {line!r}"

    def test_line_count_preserved(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = fixture_lines('mixed.txt')
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert len(stdout.splitlines()) == len(lines)
