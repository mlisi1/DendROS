"""Tests for lib/param_watcher.py — param change notification subsystem."""

import os
import queue
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'dendROS'))

import lib.param_watcher as pw
from conftest import strip_ansi


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_node_mock(node, color_map, tag_map):
    """Minimal stand-in for lib.config_loader.resolve_node (exact basename match)."""
    basename = node.rsplit('/', 1)[-1]
    code = color_map.get(node) or color_map.get(basename)
    label = tag_map.get(node) or tag_map.get(basename) if code else None
    return code, label


def _make_param_event(node, changed=None, new=None, deleted=None):
    """Build a list of YAML lines representing one ParameterEvent message."""
    lines = [f'node: {node}', 'stamp:', '  sec: 0', '  nanosec: 0']
    for section, params in [('new_parameters', new), ('changed_parameters', changed),
                             ('deleted_parameters', deleted)]:
        if params:
            lines.append(f'{section}:')
            for name, type_id, val_field, val in params:
                lines += [
                    f'- name: {name}',
                    f'  value:',
                    f'    type: {type_id}',
                    f'    {val_field}: {val}',
                ]
        else:
            lines.append(f'{section}: []')
    return lines


def _drain_all(color_map, tag_map, style_map=None, tag_style='normal', show_tag=True,
               alert_style='inline'):
    """Drain the queue using the real drain() but with a mock resolve_node."""
    return pw.drain(color_map, tag_map, style_map or {}, tag_style, show_tag, alert_style)


def _flush_queue():
    while True:
        try:
            pw._queue.get_nowait()
        except queue.Empty:
            break


# ── _extract_value ────────────────────────────────────────────────────────────

class TestExtractValue:

    def test_bool_true(self):
        assert pw._extract_value({'type': 1, 'bool_value': True}) == 'true'

    def test_bool_false(self):
        assert pw._extract_value({'type': 1, 'bool_value': False}) == 'false'

    def test_integer(self):
        assert pw._extract_value({'type': 2, 'integer_value': 42}) == '42'

    def test_double(self):
        assert pw._extract_value({'type': 3, 'double_value': 3.14}) == '3.14'

    def test_string(self):
        assert pw._extract_value({'type': 4, 'string_value': 'hello'}) == 'hello'

    def test_bool_array(self):
        result = pw._extract_value({'type': 6, 'bool_array_value': [True, False]})
        assert 'True' in result or 'False' in result

    def test_long_array_truncated(self):
        big = list(range(100))
        result = pw._extract_value({'type': 7, 'integer_array_value': big})
        assert '…' in result
        assert len(result) <= pw._MAX_VALUE_LEN + 2

    def test_unknown_type_returns_empty(self):
        assert pw._extract_value({'type': 99}) == ''

    def test_non_dict_input(self):
        result = pw._extract_value('bare_string')
        assert result == 'bare_string'


# ── _process_chunk ────────────────────────────────────────────────────────────

class TestProcessChunk:

    def setup_method(self):
        _flush_queue()
        pw._param_cache.clear()

    def _process(self, lines, color_map=None, tag_map=None, scope='tracked'):
        cm = color_map or {}
        tm = tag_map or {}
        pw._process_chunk(lines, cm, tm, scope, _resolve_node_mock)

    def test_changed_param_enqueued(self):
        lines = _make_param_event(
            '/talker',
            changed=[('use_sim_time', 1, 'bool_value', 'true')],
        )
        color_map = {'talker': '32'}
        self._process(lines, color_map)
        node, name, old_val, value = pw._queue.get_nowait()
        assert node == '/talker'
        assert name == 'use_sim_time'
        assert value == 'true'
        assert old_val is None  # first-ever change for this param

    def test_new_params_not_enqueued(self):
        """new_parameters (startup declarations) must be silently ignored."""
        lines = _make_param_event(
            '/talker',
            new=[('use_sim_time', 1, 'bool_value', 'false')],
        )
        self._process(lines, {'talker': '32'})
        assert pw._queue.empty()

    def test_deleted_params_not_enqueued(self):
        lines = _make_param_event(
            '/talker',
            deleted=[('old_param', 4, 'string_value', 'gone')],
        )
        self._process(lines, {'talker': '32'})
        assert pw._queue.empty()

    def test_cli_daemon_node_filtered(self):
        lines = _make_param_event(
            '/_ros2cli_12345',
            changed=[('use_sim_time', 1, 'bool_value', 'false')],
        )
        self._process(lines, {})
        assert pw._queue.empty()

    def test_untracked_node_filtered_in_tracked_scope(self):
        lines = _make_param_event(
            '/unknown_node',
            changed=[('my_param', 2, 'integer_value', '5')],
        )
        self._process(lines, {'talker': '32'}, scope='tracked')
        assert pw._queue.empty()

    def test_untracked_node_passes_in_all_scope(self):
        lines = _make_param_event(
            '/unknown_node',
            changed=[('my_param', 2, 'integer_value', '5')],
        )
        self._process(lines, {'talker': '32'}, scope='all')
        assert not pw._queue.empty()
        node, name, old_val, value = pw._queue.get_nowait()
        assert node == '/unknown_node'
        assert name == 'my_param'

    def test_multiple_changed_params_all_enqueued(self):
        lines = _make_param_event(
            '/talker',
            changed=[
                ('param_a', 1, 'bool_value', 'true'),
                ('param_b', 2, 'integer_value', '7'),
            ],
        )
        self._process(lines, {'talker': '32'})
        assert pw._queue.qsize() == 2

    def test_invalid_yaml_silently_ignored(self):
        self._process(['not: valid: yaml: :::'], {'talker': '32'})
        # should not raise; queue stays empty
        assert pw._queue.empty()

    def test_empty_node_field_filtered(self):
        lines = ['node: ', 'changed_parameters:', '- name: p', '  value:', '    type: 1',
                 '    bool_value: true', 'new_parameters: []', 'deleted_parameters: []']
        self._process(lines, {}, scope='all')
        assert pw._queue.empty()

    def test_namespaced_node_matched_by_basename(self):
        lines = _make_param_event(
            '/my_ns/talker',
            changed=[('rate', 3, 'double_value', '10.0')],
        )
        self._process(lines, {'talker': '32'}, scope='tracked')
        assert not pw._queue.empty()

    def test_wildcard_pattern_matched(self):
        """Wildcard patterns in color_map are resolved by _resolve_node_mock (exact only)
        — this test verifies that a direct match reaches the queue."""
        lines = _make_param_event(
            '/nav2_planner',
            changed=[('max_vel', 3, 'double_value', '1.5')],
        )
        self._process(lines, {'nav2_planner': '35'}, scope='tracked')
        assert not pw._queue.empty()


# ── drain() formatting ────────────────────────────────────────────────────────

class TestDrain:

    def setup_method(self):
        _flush_queue()
        pw._param_cache.clear()

    def _push(self, node, name, value, old_val=None):
        pw._queue.put((node, name, old_val, value))

    def test_drain_empty_queue_returns_empty_list(self):
        result = _drain_all({}, {})
        assert result == []

    def test_notification_contains_node_name(self):
        self._push('/talker', 'use_sim_time', 'true')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert len(lines) == 1
        assert '/talker' in strip_ansi(lines[0])

    def test_notification_contains_param_name(self):
        self._push('/talker', 'use_sim_time', 'true')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert 'use_sim_time' in strip_ansi(lines[0])

    def test_notification_contains_value(self):
        self._push('/talker', 'use_sim_time', 'true')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert 'true' in strip_ansi(lines[0])

    def test_notification_contains_dendros_header(self):
        self._push('/talker', 'rate', '10.0')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert '[dendROS]' in strip_ansi(lines[0])

    def test_dendros_header_logo_colors(self):
        """[dendROS] must split on the logo palette: [dend in logo-blue, ROS] in logo-orange."""
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert '[dendROS]' in strip_ansi(lines[0])
        # Logo-blue (0,75,107) for '[dend'
        assert '\033[38;2;0;75;107;1m[dend' in lines[0]
        # Logo-orange (224,127,0) for 'ROS]'
        assert '\033[38;2;224;127;0;1mROS]' in lines[0]

    def test_node_colored(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert '\033[32m/talker\033[0m' in lines[0]

    def test_tag_shown_when_label_present(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': 'TLK'})
        assert '[TLK]' in lines[0]

    def test_tag_hidden_when_show_tag_false(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': 'TLK'}, show_tag=False)
        assert '[TLK]' not in lines[0]

    def test_inverted_tag_style(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all(
            {'talker': '32'}, {'talker': 'TLK'},
            style_map={'talker': 'inverted'}, tag_style='inverted',
        )
        assert '\033[32;7m[TLK]\033[0m' in lines[0]

    def test_param_name_bold(self):
        self._push('/talker', 'my_param', 'val')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert '\033[1mmy_param\033[0m' in lines[0]

    def test_param_keyword_plain_white(self):
        """'param' keyword must appear without any ANSI color code (plain/white)."""
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert 'param' in strip_ansi(lines[0])
        assert '\033[35mparam\033[0m' not in lines[0]
        assert '\033[2mparam\033[0m' not in lines[0]

    def test_untracked_node_no_color(self):
        """In 'all' mode, untracked nodes appear without ANSI color wrapping the node name."""
        self._push('/unknown_node', 'p', 'v')
        lines = _drain_all({}, {})
        assert '/unknown_node' in lines[0]
        import re
        assert not re.search(r'\033\[[0-9;]+m/unknown_node\033\[0m', lines[0])

    def test_multiple_events_all_drained(self):
        for i in range(5):
            self._push('/talker', f'param_{i}', str(i))
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert len(lines) == 5

    def test_line_ends_with_newline(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert lines[0].endswith('\n')

    def test_arrow_separator_present(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert '→' in lines[0]

    def test_unknown_old_value_shown_as_question_mark(self):
        """First-ever change (old_val=None) should show '? →' in output."""
        self._push('/talker', 'p', 'new', old_val=None)
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        assert '? →' in strip_ansi(lines[0])

    def test_known_old_value_shown(self):
        self._push('/talker', 'p', 'new', old_val='old')
        lines = _drain_all({'talker': '32'}, {'talker': ''})
        plain = strip_ansi(lines[0])
        assert 'old → new' in plain

    def test_process_chunk_caches_and_reports_old_value(self):
        """Second change via _process_chunk should carry the first change's value as old."""
        import queue as _queue_mod
        pw._param_cache.clear()
        _flush_queue()

        def _resolve(node, cm, tm):
            return cm.get(node.rsplit('/', 1)[-1]), None

        lines1 = _make_param_event('/talker', changed=[('rate', 3, 'double_value', '5.0')])
        pw._process_chunk(lines1, {'talker': '32'}, {}, 'all', _resolve)
        _, _, old1, val1 = pw._queue.get_nowait()
        assert old1 is None
        assert val1 == '5.0'

        lines2 = _make_param_event('/talker', changed=[('rate', 3, 'double_value', '10.0')])
        pw._process_chunk(lines2, {'talker': '32'}, {}, 'all', _resolve)
        _, _, old2, val2 = pw._queue.get_nowait()
        assert old2 == '5.0'
        assert val2 == '10.0'


# ── Inverted alert style ──────────────────────────────────────────────────────

class TestInvertedAlertStyle:

    def setup_method(self):
        _flush_queue()
        pw._param_cache.clear()

    def _push(self, node, name, value, old_val=None):
        pw._queue.put((node, name, old_val, value))

    def test_inverted_sections_use_correct_backgrounds(self):
        """Node identity uses explicit node-color bg; everything else on white bg."""
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        # Node identity: explicit green bg + black text (_fg_to_bg('32') == '42')
        assert '\033[42;30m' in lines[0]
        # White bg present (for param section and separating spaces)
        assert '\033[107;30m' in lines[0]
        # No reverse-video for node identity
        assert '\033[32;7m' not in lines[0]

    def test_inverted_contains_node_name(self):
        self._push('/talker', 'use_sim_time', 'true')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert '/talker' in strip_ansi(lines[0])

    def test_inverted_contains_param_name(self):
        self._push('/talker', 'use_sim_time', 'true')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert 'use_sim_time' in strip_ansi(lines[0])

    def test_inverted_contains_value(self):
        self._push('/talker', 'use_sim_time', 'true')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert 'true' in strip_ansi(lines[0])

    def test_inverted_tag_and_node_use_explicit_node_bg(self):
        """Tag and node name together in one colored-bg island (_fg_to_bg of node code)."""
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': 'TLK'}, alert_style='inverted')
        assert '[TLK]' in strip_ansi(lines[0])
        # _fg_to_bg('32') == '42' → green bg + black text; returns to white bg (_WB) after
        assert '\033[42;30m[TLK] /talker\033[107;30m' in lines[0]

    def test_inverted_tag_hidden_when_show_tag_false(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': 'TLK'},
                           show_tag=False, alert_style='inverted')
        assert '[TLK]' not in strip_ansi(lines[0])

    def test_inverted_no_param_bold_marker(self):
        """Inverted block wraps everything; no standalone bold param marker needed."""
        self._push('/talker', 'my_param', 'val')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        # Content must still contain the param name
        assert 'my_param' in strip_ansi(lines[0])

    def test_inverted_untracked_uses_explicit_white_bg(self):
        """Untracked nodes (all mode) get the white bg strip; no reverse-video or color bg."""
        self._push('/unknown', 'p', 'v')
        lines = _drain_all({}, {}, alert_style='inverted')
        assert '\033[107;30m' in lines[0]  # white bg present
        assert '\033[7m' not in lines[0]   # no reverse-video at all
        # No node-color bg escape (no fg→bg conversion applied for untracked)
        import re
        assert not re.search(r'\033\[4[0-9];30m', lines[0])

    def test_inverted_block_reset_at_end(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert '\033[0m' in lines[0]

    def test_inverted_extends_to_eol_with_erase_sequence(self):
        """\\033[K (erase to EOL) must be present to fill background to console edge."""
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert '\033[K' in lines[0]

    def test_inverted_dendros_header_present(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert '[dendROS]' in strip_ansi(lines[0])

    def test_inverted_dendros_header_logo_colors(self):
        """[dend on logo-blue bg, ROS] on logo-orange bg; black text (hollow/cutout)."""
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert '\033[48;2;0;75;107;1m' in lines[0]   # logo-blue background
        assert '\033[48;2;224;127;0;1m' in lines[0]  # logo-orange background
        # Black text applied before [dend (hollow cutout look)
        assert '\033[48;2;0;75;107;1m\033[30m[dend' in lines[0]

    def test_inverted_arrow_present(self):
        self._push('/talker', 'p', 'v')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert '→' in strip_ansi(lines[0])

    def test_inverted_same_content_as_inline(self):
        """Both styles must expose the same semantic content in plain text."""
        self._push('/talker', 'use_sim_time', 'true', old_val='false')
        inline_lines = _drain_all({'talker': '32'}, {'talker': 'CTR'}, alert_style='inline')
        self._push('/talker', 'use_sim_time', 'true', old_val='false')
        inv_lines = _drain_all({'talker': '32'}, {'talker': 'CTR'}, alert_style='inverted')
        assert strip_ansi(inline_lines[0]).strip() == strip_ansi(inv_lines[0]).strip()

    def test_inverted_old_value_unknown_shows_question_mark(self):
        self._push('/talker', 'p', 'new', old_val=None)
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert '? →' in strip_ansi(lines[0])

    def test_inverted_known_old_value_shown(self):
        self._push('/talker', 'p', 'new', old_val='old')
        lines = _drain_all({'talker': '32'}, {'talker': ''}, alert_style='inverted')
        assert 'old → new' in strip_ansi(lines[0])


# ── Global config defaults ────────────────────────────────────────────────────

class TestGlobalConfigDefaults:

    def test_param_change_alert_default_false(self):
        from lib.global_config import DEFAULTS
        assert DEFAULTS['param_change_alert'] is False

    def test_param_change_alert_scope_default_tracked(self):
        from lib.global_config import DEFAULTS
        assert DEFAULTS['param_change_alert_scope'] == 'tracked'

    def test_param_change_alert_style_default_inline(self):
        from lib.global_config import DEFAULTS
        assert DEFAULTS['param_change_alert_style'] == 'inline'

    def test_all_keys_present_in_defaults(self):
        from lib.global_config import DEFAULTS
        assert 'param_change_alert' in DEFAULTS
        assert 'param_change_alert_scope' in DEFAULTS
        assert 'param_change_alert_style' in DEFAULTS
