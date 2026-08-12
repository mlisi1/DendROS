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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from lib.console_commands import (
    canonical_node_name,
    focus_predicate,
    line_matches_node,
    node_identity_names,
    parse_console_command,
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
