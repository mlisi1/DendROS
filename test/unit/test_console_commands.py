"""Tests for lib/console_commands.py — the pure/testable layer backing the TUI launch
mode's `\\`-console (see lib/launch_tui_console.py's _TuiConsoleMixin, curses-owning and
manual-testing only, same accepted gap as the rest of the TUI's curses layer).

Node identity (node_name/logger_name) is NOT reverse-parsed from rendered text here — it's
threaded through from dendROS_pipe.py's own colorization pipeline (see console_commands.py's
module docstring) — so these tests exercise the identity-matching functions directly against
(node_name, logger_name) pairs, not against sample colorized log lines.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from lib.console_commands import (
    build_filter,
    canonical_node_name,
    drop_mode,
    focus_predicate,
    format_filter_status,
    format_mute_status,
    mute_predicate,
    grep_predicate,
    level_predicate,
    line_level,
    parse_level,
    line_matches_node,
    node_identity_names,
    parse_console_command,
    push_mode,
)


# ── canonical_node_name() ────────────────────────────────────────────────────────

class TestCanonicalNodeName:
    def test_strips_leading_slash(self):
        assert canonical_node_name('/talker') == 'talker'

    def test_leaves_bare_name_unchanged(self):
        assert canonical_node_name('talker') == 'talker'

    def test_only_strips_one_leading_slash(self):
        # Namespaced nodes (e.g. '/ns/talker') keep their internal structure -- only the
        # single leading root-namespace slash is stripped.
        assert canonical_node_name('/ns/talker') == 'ns/talker'


# ── node_identity_names() ────────────────────────────────────────────────────────

class TestNodeIdentityNames:
    def test_plain_node_yields_both_names_normalized(self):
        # node_name and logger_name coincide (modulo the leading slash) for a plain,
        # non-composable node.
        assert node_identity_names('talker', '/talker') == {'talker'}

    def test_composable_node_yields_container_and_component(self):
        # A composable node's node_name is its container's process tag; its own graph
        # name only shows up as logger_name.
        assert node_identity_names('component_container', 'lidar_driver') == {
            'component_container', 'lidar_driver',
        }

    def test_diverging_names_both_included(self):
        # slam_toolbox launched as slam_node still logs under its own hard-coded name.
        assert node_identity_names('slam_node', 'slam_toolbox') == {'slam_node', 'slam_toolbox'}

    def test_node_name_only(self):
        assert node_identity_names('talker', None) == {'talker'}

    def test_logger_name_only(self):
        assert node_identity_names(None, 'talker') == {'talker'}

    def test_both_none_yields_empty_set(self):
        assert node_identity_names(None, None) == set()

    def test_normalizes_leading_slash_on_both(self):
        assert node_identity_names('/talker', '/talker') == {'talker'}


# ── line_matches_node() ──────────────────────────────────────────────────────────

class TestLineMatchesNode:
    def test_matches_by_node_name(self):
        assert line_matches_node('talker', None, 'talker') is True

    def test_matches_by_logger_name(self):
        assert line_matches_node(None, 'talker', 'talker') is True

    def test_composable_node_matches_by_component_name_not_container(self):
        assert line_matches_node('component_container', 'lidar_driver', 'lidar_driver') is True

    def test_composable_node_also_matches_by_container_name(self):
        assert line_matches_node('component_container', 'lidar_driver', 'component_container') is True

    def test_does_not_match_unrelated_name(self):
        assert line_matches_node('component_container', 'lidar_driver', 'camera_driver') is False

    def test_both_none_never_matches(self):
        assert line_matches_node(None, None, 'talker') is False

    def test_matches_regardless_of_leading_slash(self):
        # logger_name as discovered upstream may carry a leading '/'; target is expected
        # to already be canonical_node_name()-normalized by the caller.
        assert line_matches_node(None, '/talker', 'talker') is True


# ── focus_predicate() ────────────────────────────────────────────────────────────

class TestFocusPredicate:
    def test_delegates_to_line_matches_node(self):
        assert focus_predicate('irrelevant text', 'talker', None, 'talker') is True
        assert focus_predicate('irrelevant text', 'listener', None, 'talker') is False

    def test_plain_text_argument_is_ignored(self):
        # The predicate signature is fixed by RingLog.set_filter(), but matching is
        # purely identity-based -- plain_text content must never affect the result.
        assert focus_predicate('talker mentioned here', 'listener', None, 'talker') is False


# ── parse_console_command() ──────────────────────────────────────────────────────

class TestParseConsoleCommand:
    def test_command_with_arg(self):
        assert parse_console_command("focus talker") == ('focus', 'talker')

    def test_command_without_arg(self):
        assert parse_console_command("clear") == ('clear', '')

    def test_normalizes_internal_and_surrounding_whitespace(self):
        assert parse_console_command("  focus    talker  ") == ('focus', 'talker')

    def test_empty_input_returns_none_command(self):
        assert parse_console_command("") == (None, '')

    def test_whitespace_only_input_returns_none_command(self):
        assert parse_console_command("   ") == (None, '')

    def test_command_name_is_case_insensitive(self):
        assert parse_console_command("FOCUS talker") == ('focus', 'talker')

    def test_multi_word_arg_preserved_verbatim(self):
        assert parse_console_command("focus a b") == ('focus', 'a b')



# ── grep_predicate() ─────────────────────────────────────────────────────────────

class TestGrepPredicate:
    def test_substring_match(self):
        assert grep_predicate("[talker-1] [INFO]: goal reached", None, None, "goal")

    def test_non_match(self):
        assert not grep_predicate("[talker-1] [INFO]: hello", None, None, "goal")

    def test_lowercase_query_is_case_insensitive(self):
        assert grep_predicate("Timeout waiting", None, None, "timeout")

    def test_uppercase_query_is_case_sensitive(self):
        assert grep_predicate("Timeout waiting", None, None, "Timeout")
        assert not grep_predicate("timeout waiting", None, None, "Timeout")

    def test_matches_text_not_node_identity(self):
        # A line from node "planner" without the word in its text doesn't match.
        assert not grep_predicate("[INFO]: hello", "planner", "planner", "planner")


# ── build_filter() ───────────────────────────────────────────────────────────────

class TestBuildFilter:
    def test_no_filters_is_none(self):
        assert build_filter() is None
        assert build_filter(None, '') is None

    def test_focus_only(self):
        pred = build_filter('talker', None)
        assert pred("anything", "talker", "talker")
        assert not pred("anything", "listener", "listener")

    def test_grep_only(self):
        pred = build_filter(None, 'goal')
        assert pred("goal reached", "listener", "listener")
        assert not pred("hello", "listener", "listener")

    def test_focus_and_grep_must_both_hold(self):
        pred = build_filter('talker', 'goal')
        assert pred("goal reached", "talker", "talker")
        assert not pred("goal reached", "listener", "listener")  # wrong node
        assert not pred("hello", "talker", "talker")              # no text match

    def test_composable_node_via_logger_name(self):
        pred = build_filter('lidar_driver', 'scan')
        assert pred("scan ok", "container", "/lidar_driver")


# ── format_filter_status() ───────────────────────────────────────────────────────

class TestFormatFilterStatus:
    def test_none_when_unfiltered(self):
        assert format_filter_status() is None

    def test_focus_only(self):
        assert format_filter_status('talker', None) == 'focus talker'

    def test_grep_only(self):
        assert format_filter_status(None, 'goal') == 'grep "goal"'

    def test_both(self):
        assert format_filter_status('talker', 'goal') == 'focus talker · grep "goal"'



# ── push_mode() / drop_mode() — Esc mode stack ───────────────────────────────────

class TestModeStack:
    def test_push_appends_in_activation_order(self):
        assert push_mode(push_mode([], 'focus'), 'grep') == ['focus', 'grep']

    def test_reactivating_moves_to_top_without_duplicate(self):
        # focus, grep, then a new focus target: Esc must exit focus first now.
        assert push_mode(['focus', 'grep'], 'focus') == ['grep', 'focus']

    def test_drop_removes_from_anywhere(self):
        assert drop_mode(['focus', 'find', 'grep'], 'find') == ['focus', 'grep']

    def test_drop_inactive_is_noop(self):
        assert drop_mode(['grep'], 'focus') == ['grep']

    def test_pure_does_not_mutate_input(self):
        stack = ['focus']
        push_mode(stack, 'grep')
        drop_mode(stack, 'focus')
        assert stack == ['focus']



# ── level: parse_level() / line_level() / level_predicate() ──────────────────────

class TestParseLevel:
    @pytest.mark.parametrize('text,expected', [
        ('debug', 'debug'), ('info', 'info'), ('warn', 'warn'), ('error', 'error'),
        ('fatal', 'fatal'), ('WARN', 'warn'), ('warning', 'warn'), ('  Error ', 'error'),
    ])
    def test_valid(self, text, expected):
        assert parse_level(text) == expected

    @pytest.mark.parametrize('text', ['', 'warnn', 'critical', '3'])
    def test_invalid(self, text):
        assert parse_level(text) is None


class TestLineLevel:
    def test_node_output_full_metadata(self):
        assert line_level('[talker-1] [WARN] [1700000000.1] [talker]: low battery') == 2

    def test_node_output_metadata_stripped(self):
        # show_timestamp/show_logger_name: false still keep the [LEVEL] bracket.
        assert line_level('[talker-1] [ERROR]: boom') == 3

    def test_tag_before_badge(self):
        assert line_level('[LOC] [slam_node-2] [INFO]: ok') == 1

    def test_launch_framework_line(self):
        assert line_level('[ERROR] [talker-1]: process has died [pid 42, exit code 1]') == 3

    def test_warning_spelling(self):
        assert line_level('[WARNING] [launch]: something') == 2

    def test_message_text_cannot_outrank_real_level(self):
        assert line_level('[talker-1] [INFO] [t] [talker]: saw [FATAL] in a string') == 1

    def test_no_level(self):
        assert line_level('Traceback (most recent call last):') is None
        assert line_level('  File "x.py", line 3, in <module>') is None
        assert line_level('plain print output') is None


class TestLevelPredicate:
    def test_at_threshold_passes(self):
        assert level_predicate('[a-1] [WARN]: x', None, None, 'warn')

    def test_above_threshold_passes(self):
        assert level_predicate('[a-1] [FATAL]: x', None, None, 'warn')

    def test_below_threshold_hidden(self):
        assert not level_predicate('[a-1] [INFO]: x', None, None, 'warn')
        assert not level_predicate('[a-1] [DEBUG]: x', None, None, 'info')

    def test_level_less_lines_always_pass(self):
        # Never hide tracebacks/crash output behind a severity filter.
        assert level_predicate('Traceback (most recent call last):', None, None, 'fatal')

    def test_combined_with_focus_and_grep(self):
        pred = build_filter('talker', 'battery', 'warn')
        assert pred('[talker-1] [WARN]: low battery', 'talker', 'talker')
        assert not pred('[talker-1] [INFO]: low battery', 'talker', 'talker')    # level
        assert not pred('[talker-1] [WARN]: overheating', 'talker', 'talker')    # grep
        assert not pred('[other-2] [WARN]: low battery', 'other', 'other')       # focus

    def test_status_chip_order(self):
        assert format_filter_status('talker', 'x', 'warn') == 'focus talker · level warn · grep "x"'
        assert format_filter_status(None, None, 'error') == 'level error'



# ── mute: mute_predicate() / format_mute_status() / build_filter(muted=…) ─────────

class TestMute:
    def test_muted_node_hidden(self):
        assert not mute_predicate('x', 'talker', 'talker', {'talker'})

    def test_other_nodes_and_level_less_lines_pass(self):
        assert mute_predicate('x', 'listener', 'listener', {'talker'})
        assert mute_predicate('Traceback (most recent call last):', None, None, {'talker'})

    def test_muting_container_hides_its_components(self):
        assert not mute_predicate('x', 'container', 'lidar_driver', {'container'})

    def test_muting_component_hides_only_it(self):
        muted = {'lidar_driver'}
        assert not mute_predicate('x', 'container', '/lidar_driver', muted)
        assert mute_predicate('x', 'container', 'camera_driver', muted)

    def test_build_filter_mutes_under_other_filters(self):
        pred = build_filter(None, 'goal', None, {'talker'})
        assert not pred('goal', 'talker', 'talker')
        assert pred('goal', 'listener', 'listener')
        assert not pred('other', 'listener', 'listener')

    def test_build_filter_snapshot_of_muted_set(self):
        # The predicate must not change under the ring when the set is later mutated —
        # the caller rebuilds the filter through _apply_filters() instead.
        muted = {'talker'}
        pred = build_filter(muted=muted)
        muted.clear()
        assert not pred('x', 'talker', 'talker')

    def test_empty_muted_is_no_filter(self):
        assert build_filter(muted=set()) is None

    def test_status_text(self):
        assert format_mute_status(set()) is None
        assert format_mute_status({'a'}) == '1 node muted'
        assert format_mute_status({'a', 'b'}) == '2 nodes muted'
