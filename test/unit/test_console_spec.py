"""Tests for lib/console_spec.py — the TUI console's command specs, Tab completion
(Completer/completion_context) and the help overlay's pure layout (help_rows)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from lib.console_spec import (
    COMMAND_NAMES,
    COMMANDS,
    KEYS,
    Completer,
    completion_context,
    help_rows,
)
from lib.launch_tui_console import _TuiConsoleMixin

NODES = {'talker', 'talker_2', 'listener', 'lidar_driver', 'Planner'}


class TestSpecsMatchHandlers:
    def test_every_spec_has_a_handler_and_vice_versa(self):
        # Help and completion must never advertise a command that doesn't exist, or miss one.
        assert set(COMMAND_NAMES) == set(_TuiConsoleMixin._COMMAND_HANDLERS)

    def test_usage_starts_with_name(self):
        for spec in COMMANDS:
            assert spec.usage.split()[0] == spec.name


class TestCompletionContext:
    def test_empty_buffer_completes_commands(self):
        head, prefix, pool, smart_case = completion_context('')
        assert (head, prefix) == ('', '')
        assert pool == [n + ' ' for n in COMMAND_NAMES]
        assert smart_case is False

    def test_partial_command(self):
        assert completion_context('fo')[:2] == ('', 'fo')

    def test_node_argument(self):
        head, prefix, pool, smart_case = completion_context('focus ta', NODES)
        assert (head, prefix) == ('focus ', 'ta')
        assert pool == sorted(NODES)
        assert smart_case is True

    def test_node_argument_leading_slash_ignored(self):
        assert completion_context('focus /ta', NODES)[1] == 'ta'

    def test_level_argument(self):
        assert completion_context('level w')[2] == ['debug', 'info', 'warn', 'error', 'fatal']

    def test_text_arguments_have_no_candidates(self):
        assert completion_context('grep foo')[2] == []
        assert completion_context('find foo')[2] == []

    def test_unknown_command_has_no_candidates(self):
        assert completion_context('bogus x')[2] == []


class TestCompleter:
    def test_unique_command_completes_with_space(self):
        assert Completer().tab('fo') == 'focus '

    def test_command_is_case_insensitive(self):
        assert Completer().tab('LE') == 'level '

    def test_ambiguous_extends_to_common_prefix_and_lists(self):
        c = Completer()
        assert c.tab('focus t', NODES) == 'focus talker'
        assert c.candidates == ['talker', 'talker_2']
        assert c.index is None

    def test_repeated_tab_cycles_and_wraps(self):
        c = Completer()
        buf = c.tab('focus t', NODES)
        buf = c.tab(buf, NODES)
        assert (buf, c.index) == ('focus talker', 0)
        buf = c.tab(buf, NODES)
        assert (buf, c.index) == ('focus talker_2', 1)
        buf = c.tab(buf, NODES)
        assert (buf, c.index) == ('focus talker', 0)

    def test_shift_tab_cycles_backwards(self):
        c = Completer()
        buf = c.tab('focus t', NODES)
        assert c.tab(buf, NODES, backwards=True) == 'focus talker_2'

    def test_edit_breaks_the_cycle(self):
        c = Completer()
        buf = c.tab('focus t', NODES)
        # User typed '_' after the completion: fresh completion, not a cycle step.
        assert c.tab(buf + '_', NODES) == 'focus talker_2'
        assert c.candidates == []

    def test_reset_clears_candidates(self):
        c = Completer()
        c.tab('focus t', NODES)
        c.reset()
        assert c.candidates == [] and c.index is None

    def test_no_match_leaves_buffer(self):
        c = Completer()
        assert c.tab('focus zzz', NODES) == 'focus zzz'
        assert c.candidates == []

    def test_smart_case_node(self):
        assert Completer().tab('focus pl', NODES) == 'focus Planner'
        assert Completer().tab('focus Pl', NODES) == 'focus Planner'
        assert Completer().tab('focus PL', NODES) == 'focus PL'  # uppercase = exact case, no match

    def test_level_completion(self):
        assert Completer().tab('level e') == 'level error'
        assert Completer().tab('level W') == 'level warn'  # levels are case-insensitive

    def test_ambiguous_commands_cycle_with_trailing_space(self):
        c = Completer()
        buf = c.tab('f')  # focus, find
        assert buf == 'f' and c.candidates == ['find ', 'focus ']
        assert c.tab(buf) == 'find '

    def test_text_command_argument_untouched(self):
        assert Completer().tab('grep tal', NODES) == 'grep tal'


class TestHelpRows:
    def _text(self, rows):
        return [''.join(t for t, _ in row) for row in rows]

    def test_lists_every_command_and_key(self):
        text = '\n'.join(self._text(help_rows(80)))
        for spec in COMMANDS:
            assert spec.usage in text
        for key, _ in KEYS:
            assert key in text

    def test_sections_styled(self):
        rows = help_rows(80)
        sections = [row[0][0] for row in rows if row and row[0][1] == 'section']
        assert sections == ['Commands', 'Keys']

    def test_rows_fit_width(self):
        for width in (20, 40, 80):
            assert all(len(line) <= width for line in self._text(help_rows(width)))

    def test_narrow_width_wraps_descriptions_under_their_column(self):
        rows = help_rows(40)
        continuation = [row for row in rows if len(row) == 2 and row[0][0].strip() == '']
        assert continuation, 'expected wrapped description rows'
        key_w = len(rows[1][0][0])
        assert all(len(row[0][0]) == key_w for row in continuation)
