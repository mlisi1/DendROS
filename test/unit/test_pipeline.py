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
        from lib.colors import _resolve_color
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
        from lib.colors import _resolve_color
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
        from lib.colors import _resolve_color
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


# ── wildcard node matching ────────────────────────────────────────────────────

class TestWildcardPipeline:
    PKG = 'test_pkg_wc'

    def test_wildcard_suffix_colors_matching_node(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('wildcards.yaml'))
        from lib.colors import _resolve_color
        nav_code = _resolve_color('bold green')
        lines = ["[nav2_controller-1] [INFO] [1.0] [n]: Planning\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[nav2_controller-1]', nav_code)

    def test_wildcard_matches_second_node_same_pattern(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('wildcards.yaml'))
        from lib.colors import _resolve_color
        nav_code = _resolve_color('bold green')
        lines = ["[nav2_planner-1] [INFO] [1.0] [n]: Computing path\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[nav2_planner-1]', nav_code)

    def test_non_matching_node_passes_through(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('wildcards.yaml'))
        lines = ["[other_node-1] [INFO] [1.0] [o]: message\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert not ANSI_RE.search(stdout)

    def test_wildcard_namespace_pattern_matches(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('wildcards.yaml'))
        from lib.colors import _resolve_color
        loc_code = _resolve_color('bold blue')
        lines = ["[/robot/amcl-1] [INFO] [1.0] [a]: Localizing\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[/robot/amcl-1]', loc_code)

    def test_wildcard_badge_inserted(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('wildcards.yaml'))
        lines = ["[nav2_controller-1] [INFO] [1.0] [n]: msg\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[NAV]' in stdout

    def test_message_text_uncolored_with_wildcard(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('wildcards.yaml'))
        lines = ["[nav2_controller-1] [INFO] [1.0] [n]: Planning route\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_uncolored(stdout, 'Planning route')

    def test_wildcard_launch_framework_line(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('wildcards.yaml'))
        from lib.colors import _resolve_color
        nav_code = _resolve_color('bold green')
        lines = ["[INFO] [nav2_controller-1]: process started with pid [1234]\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[nav2_controller-1]', nav_code)


# ── per-group show_tag override ───────────────────────────────────────────────

class TestPerGroupShowTag:
    PKG = 'test_pkg_show_tag'

    def test_badge_shown_for_group_with_tag(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('per_group_show_tag.yaml'))
        lines = ["[nav2_controller-1] [INFO] [1.0] [n]: planning\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[NAV]' in stdout

    def test_badge_suppressed_for_show_tag_false_group(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('per_group_show_tag.yaml'))
        lines = ["[robot_state_publisher-1] [INFO] [1.0] [r]: publishing\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[HW]' not in stdout

    def test_color_still_applied_when_show_tag_false(self, tmp_path):
        from lib.colors import _resolve_color
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('per_group_show_tag.yaml'))
        lines = ["[robot_state_publisher-1] [INFO] [1.0] [r]: publishing\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        hw_code = _resolve_color('dark yellow')
        assert_segment_colored(stdout, '[robot_state_publisher-1]', hw_code)


# ── per-group color_mode override ─────────────────────────────────────────────

class TestPerGroupColorMode:
    PKG = 'test_pkg_group_mode'

    def test_hardware_group_full_line_colors_whole_line(self, tmp_path):
        from lib.colors import _resolve_color
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('per_group_color_mode.yaml'))
        hw_code = _resolve_color('dark yellow')
        lines = ["[robot_state_publisher-1] [INFO] [1.0] [r]: publishing\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        # full_line wraps the entire line — both prefix and message share one segment
        segs = colored_segments(stdout)
        assert any(hw_code == code and '[robot_state_publisher-1]' in text
                   for text, code in segs)
        assert any(hw_code == code and 'publishing' in text
                   for text, code in segs)

    def test_nav_group_tag_only_preserves_message(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('per_group_color_mode.yaml'))
        lines = ["[nav2_controller-1] [INFO] [1.0] [n]: planning\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_uncolored(stdout, 'planning')


# ── unmatched_tag ─────────────────────────────────────────────────────────────

class TestUnmatchedTag:
    PKG = 'test_pkg_unmatched_tag'

    def test_badge_shown_for_unmatched_node(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('unmatched_tag.yaml'))
        lines = ["[unknown_node-1] [INFO] [1.0] [u]: hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[?]' in stdout

    def test_unmatched_color_applied(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('unmatched_tag.yaml'))
        lines = ["[unknown_node-1] [INFO] [1.0] [u]: hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '\033[' in stdout  # some color applied

    def test_matched_node_no_unmatched_badge(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('unmatched_tag.yaml'))
        lines = ["[nav2_controller-1] [INFO] [1.0] [n]: planning\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert '[?]' not in stdout


# ── dim_unmatched ─────────────────────────────────────────────────────────────

class TestDimUnmatched:
    PKG = 'test_pkg_dim'

    def test_unmatched_node_dimmed(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('dim_unmatched.yaml'))
        lines = ["[unknown_node-1] [INFO] [1.0] [u]: hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[unknown_node-1]', '2')

    def test_matched_node_not_dimmed(self, tmp_path):
        from lib.colors import _resolve_color
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('dim_unmatched.yaml'))
        nav_code = _resolve_color('bold green')
        lines = ["[nav2_controller-1] [INFO] [1.0] [n]: planning\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[nav2_controller-1]', nav_code)


# ── Crash alert: death detection ──────────────────────────────────────────────

class TestCrashAlertDetection:
    """Unit tests for _detect_death — pure function, no subprocess needed."""

    def _detect(self, line):
        from lib.crash_alert import detect_death
        return detect_death(line)   # returns (node_name, exit_code) or (None, None)

    def _node(self, line):
        return self._detect(line)[0]

    def _ec(self, line):
        return self._detect(line)[1]

    # ── process has died — node-output format ─────────────────────────────────

    def test_detects_process_has_died(self):
        line = "[my_node-1]: process has died [pid 1234, exit code -11, cmd '/path/node' ; ]\n"
        assert self._node(line) == 'my_node'

    def test_captures_exit_code_from_died_msg(self):
        line = "[my_node-1]: process has died [pid 1234, exit code 1, cmd '...' ; ]\n"
        assert self._ec(line) == '1'

    def test_detects_process_has_died_no_suffix(self):
        line = "[slam_toolbox]: process has died\n"
        assert self._node(line) == 'slam_toolbox'

    def test_detects_process_has_died_numeric_suffix(self):
        line = "[nav2_controller-3]: process has died [pid 5678, exit code 1]\n"
        assert self._node(line) == 'nav2_controller'

    def test_detects_process_has_died_dotted_name(self):
        line = "[my.namespace.node-1]: process has died\n"
        assert self._node(line) == 'my.namespace.node'

    def test_detects_process_has_died_slash_in_name(self):
        line = "[ns/talker-2]: process has died\n"
        assert self._node(line) == 'ns/talker'

    # ── process has died — launch-framework format ────────────────────────────

    def test_detects_died_in_launch_info_format(self):
        line = "[INFO] [controller_server-4]: process has died [pid 171973, exit code 1, cmd '...']\n"
        assert self._node(line) == 'controller_server'

    def test_detects_died_in_launch_error_format(self):
        line = "[ERROR] [bt_navigator-5]: process has died [pid 9, exit code 2]\n"
        assert self._node(line) == 'bt_navigator'

    def test_launch_format_captures_exit_code(self):
        line = "[ERROR] [controller_server-4]: process has died [pid 1, exit code 1, cmd '/bin/node']\n"
        assert self._ec(line) == '1'

    def test_error_keyword_not_captured_as_node(self):
        line = "[ERROR] [controller_server-4]: process has died [pid 1, exit code 1]\n"
        assert self._node(line) != 'ERROR'

    # ── non-zero exit code ────────────────────────────────────────────────────

    def test_detects_nonzero_exit_code(self):
        line = "[my_node-1] process exited with return code: 1\n"
        assert self._node(line) == 'my_node'

    def test_captures_return_code_value(self):
        line = "[my_node-1] process exited with return code: 42\n"
        assert self._ec(line) == '42'

    def test_detects_negative_exit_code(self):
        line = "[my_node-1] process exited with return code: -11\n"
        assert self._node(line) == 'my_node'

    def test_zero_exit_code_not_detected(self):
        line = "[my_node-1] process exited with return code: 0\n"
        assert self._node(line) is None

    # ── normal lines should not trigger ──────────────────────────────────────

    def test_normal_log_line_not_detected(self):
        line = "[my_node-1] [INFO] [1234.5] [/logger]: hello world\n"
        assert self._node(line) is None

    def test_launch_started_line_not_detected(self):
        line = "[INFO] [my_node-1]: process started with pid [1234]\n"
        assert self._node(line) is None

    def test_empty_line_not_detected(self):
        node, ec = self._detect("\n")
        assert node is None and ec is None

    def test_arbitrary_text_not_detected(self):
        node, ec = self._detect("nothing here\n")
        assert node is None and ec is None

    # ── pipeline passthrough ──────────────────────────────────────────────────

    def test_death_line_still_passes_through(self, tmp_path):
        """The death message is written to stdout unchanged (colorized if matched)."""
        prefix = make_prefix(tmp_path, 'test_pkg', fixture_config('basic.yaml'))
        death_line = "[talker-1]: process has died [pid 9, exit code -11]\n"
        stdout, _, rc = run_pipe(prefix, 'test_pkg', [death_line])
        # Output must contain the original text (modulo ANSI wrapping)
        assert 'process has died' in strip_ansi(stdout)
        assert rc == 0

    def test_pipe_survives_death_lines_without_tty(self, tmp_path):
        """Pipe must not crash when crash_alert is off (default) and death lines arrive."""
        prefix = make_prefix(tmp_path, 'test_pkg', fixture_config('basic.yaml'))
        lines = [
            "[talker-1]: process has died [pid 9, exit code -11]\n",
            "[listener-2] process exited with return code: 1\n",
            "[talker-1] [INFO] [1.0] [/t]: hello\n",
        ]
        stdout, stderr, rc = run_pipe(prefix, 'test_pkg', lines)
        # All three lines must reach stdout
        plain = strip_ansi(stdout)
        assert 'process has died' in plain
        assert 'process exited with return code: 1' in plain
        assert 'hello' in plain
        assert rc == 0


class TestTracebackColorization:
    """The pipe should colorize Python traceback blocks in dim red."""

    def _run(self, lines, tmp_path):
        prefix = make_prefix(tmp_path, 'test_pkg', fixture_config('basic.yaml'))
        stdout, _, rc = run_pipe(prefix, 'test_pkg', lines)
        assert rc == 0
        return stdout

    def test_traceback_header_gets_bold_red(self, tmp_path):
        out = self._run(["Traceback (most recent call last):\n"], tmp_path)
        # Header line is bold red, not dim
        assert '\033[31;1m' in out
        assert '\033[31;2m' not in out
        assert 'Traceback' in out

    def test_traceback_frame_gets_dim_red(self, tmp_path):
        lines = [
            "Traceback (most recent call last):\n",
            '  File "/path/to/node.py", line 23, in run\n',
        ]
        out = self._run(lines, tmp_path)
        # Frame line is dim red
        assert '\033[31;2m' in out

    def test_exception_line_gets_bold_red(self, tmp_path):
        lines = [
            "Traceback (most recent call last):\n",
            "  File \"/node.py\", line 1, in f\n",
            "RuntimeError: something failed\n",
        ]
        out = self._run(lines, tmp_path)
        assert '\033[31;1m' in out
        assert 'RuntimeError' in out

    def test_node_lines_not_affected_by_traceback_state(self, tmp_path):
        lines = [
            "Traceback (most recent call last):\n",
            "  File \"/node.py\", line 1, in f\n",
            "RuntimeError: something failed\n",
            "[talker-1] [INFO] [1.0] [/t]: hello\n",
        ]
        out = self._run(lines, tmp_path)
        # Node line after traceback must still be colorized with its own color
        segs = colored_segments(out)
        hello_seg = next((s for s in segs if 'hello' in s[0]), None)
        assert hello_seg is not None

    def test_normal_lines_not_affected(self, tmp_path):
        lines = ["[talker-1] [INFO] [1.0] [/t]: hello\n"]
        out = self._run(lines, tmp_path)
        assert 'Traceback' not in out
        # No dim red from traceback path (though node may have its own color)
        assert '\033[31;2m' not in out

    def test_blank_line_ends_traceback(self, tmp_path):
        lines = [
            "Traceback (most recent call last):\n",
            "  File \"/node.py\", line 1, in f\n",
            "\n",
            "Some normal output\n",
        ]
        out = self._run(lines, tmp_path)
        assert '\033[31;2mSome normal output' not in out


def _write_global_cfg(prefix, **kwargs):
    """Write a minimal global config under prefix/.config/dendROS/defaults.yaml."""
    import yaml as _yaml
    cfg_dir = os.path.join(prefix, '.config', 'dendROS')
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, 'defaults.yaml'), 'w') as fh:
        _yaml.dump(kwargs, fh)


class TestTracebackColorModes:
    """traceback_color: fancy / red / off modes."""

    TB_LINES = [
        "Traceback (most recent call last):\n",
        '  File "/node.py", line 1, in f\n',
        "RuntimeError: boom\n",
    ]

    def _run_with_cfg(self, lines, tmp_path, **cfg):
        prefix = make_prefix(tmp_path, 'test_pkg', fixture_config('basic.yaml'))
        # run_pipe sets HOME=ament_prefix, so write the global config there
        _write_global_cfg(prefix, **cfg)
        stdout, _, rc = run_pipe(prefix, 'test_pkg', lines)
        assert rc == 0
        return stdout

    def test_fancy_header_bold_frame_dim(self, tmp_path):
        out = self._run_with_cfg(self.TB_LINES, tmp_path, traceback_color='fancy')
        assert '\033[31;1m' in out   # header + exception
        assert '\033[31;2m' in out   # frame

    def test_red_all_bold(self, tmp_path):
        out = self._run_with_cfg(self.TB_LINES, tmp_path, traceback_color='red')
        assert '\033[31;1m' in out
        assert '\033[31;2m' not in out   # no dim red — everything is bold

    def test_off_no_ansi(self, tmp_path):
        out = self._run_with_cfg(self.TB_LINES, tmp_path, traceback_color='off')
        # No red codes; text content preserved
        assert '\033[31' not in out
        assert 'Traceback' in out
        assert 'RuntimeError' in out

    def test_off_text_unchanged(self, tmp_path):
        out = self._run_with_cfg(self.TB_LINES, tmp_path, traceback_color='off')
        assert strip_ansi(out) == ''.join(self.TB_LINES)
