"""Tests for lib/tui_find.py — the pure layer behind the TUI's `\\find <text>` command.

The curses-owning side (lib/launch_tui_find.py's _TuiFindMixin) is manual-testing only, same
accepted gap as the rest of _TuiSession. Entries are RingLog.visible_entries()-shaped
(seq, row_count, plain_text) tuples, oldest-first.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from lib.tui_find import (
    is_case_sensitive,
    match_spans,
    find_matching_seqs,
    line_tail_offsets,
    center_view_offset,
    initial_match_seq,
    step_match_seq,
    match_position,
    format_find_status,
    rows_meta,
    row_highlight_spans,
)
from lib.tui_ringlog import RingLog


def _entries(*texts, start_seq=0, rows=None):
    rows = rows or [1] * len(texts)
    return [(start_seq + i, rc, t) for i, (t, rc) in enumerate(zip(texts, rows))]


class TestSmartCase:
    def test_lowercase_query_is_insensitive(self):
        assert not is_case_sensitive('timeout')

    def test_any_uppercase_makes_it_sensitive(self):
        assert is_case_sensitive('Timeout')
        assert is_case_sensitive('ERROR')

    def test_non_letters_dont_count(self):
        assert not is_case_sensitive('[info] 42')


class TestMatchSpans:
    def test_insensitive_finds_all_cases(self):
        assert match_spans('Error error ERROR', 'error') == [(0, 5), (6, 11), (12, 17)]

    def test_sensitive_only_exact_case(self):
        assert match_spans('Error error ERROR', 'Error') == [(0, 5)]

    def test_non_overlapping(self):
        assert match_spans('aaaa', 'aa') == [(0, 2), (2, 4)]

    def test_empty_query_or_no_match(self):
        assert match_spans('anything', '') == []
        assert match_spans('anything', 'zzz') == []


class TestFindMatchingSeqs:
    def test_returns_matching_seqs_oldest_first(self):
        entries = _entries('a timeout', 'ok', 'TIMEOUT again', 'fine', start_seq=10)
        assert find_matching_seqs(entries, 'timeout') == [10, 12]

    def test_smart_case_sensitive(self):
        entries = _entries('a timeout', 'TIMEOUT again')
        assert find_matching_seqs(entries, 'TIMEOUT') == [1]

    def test_empty_query(self):
        assert find_matching_seqs(_entries('x'), '') == []


class TestLineTailOffsets:
    def test_single_row_lines(self):
        entries = _entries('a', 'b', 'c')
        assert line_tail_offsets(entries, 2) == (0, 0)  # newest line sits on the tail
        assert line_tail_offsets(entries, 0) == (2, 2)

    def test_wrapped_lines_span_multiple_offsets(self):
        # seq 0: 3 rows, seq 1: 2 rows, seq 2: 1 row
        entries = _entries('a', 'b', 'c', rows=[3, 2, 1])
        assert line_tail_offsets(entries, 2) == (0, 0)
        assert line_tail_offsets(entries, 1) == (2, 1)
        assert line_tail_offsets(entries, 0) == (5, 3)

    def test_missing_seq_is_none(self):
        assert line_tail_offsets(_entries('a'), 99) is None


class TestCenterViewOffset:
    def test_puts_row_on_middle_screen_row(self):
        # log_h 10: middle row is body row 5, which has 4 rows below it.
        assert center_view_offset(50, 10, 1000) == 46

    def test_clamps_at_tail(self):
        assert center_view_offset(2, 10, 1000) == 0

    def test_clamps_at_top_of_history(self):
        assert center_view_offset(500, 10, 100) == 100


class TestInitialMatchSeq:
    def test_following_tail_picks_newest_match(self):
        entries = _entries('err', 'ok', 'err', 'ok')
        assert initial_match_seq([0, 2], entries, view_offset=0) == 2

    def test_scrolled_back_picks_newest_match_at_or_above_view_bottom(self):
        # offsets: seq3=0, seq2=1, seq1=2, seq0=3. View bottom at offset 2 → seq 2 is below.
        entries = _entries('err', 'ok', 'err', 'ok')
        assert initial_match_seq([0, 2], entries, view_offset=2) == 0

    def test_all_matches_below_view_falls_back_to_newest(self):
        entries = _entries('ok', 'ok', 'err')
        assert initial_match_seq([2], entries, view_offset=2) == 2

    def test_no_matches(self):
        assert initial_match_seq([], _entries('ok'), 0) is None


class TestStepMatchSeq:
    def test_older_and_newer(self):
        matches = [3, 7, 12]
        assert step_match_seq(matches, 12, 'older') == 7
        assert step_match_seq(matches, 7, 'newer') == 12

    def test_wraps_at_both_ends(self):
        matches = [3, 7, 12]
        assert step_match_seq(matches, 3, 'older') == 12
        assert step_match_seq(matches, 12, 'newer') == 3

    def test_steps_from_a_seq_that_is_no_longer_a_match(self):
        matches = [3, 7, 12]
        assert step_match_seq(matches, 9, 'older') == 7
        assert step_match_seq(matches, 9, 'newer') == 12
        assert step_match_seq(matches, 1, 'older') == 12  # evicted past the oldest: wrap

    def test_no_current(self):
        assert step_match_seq([3, 7], None, 'older') == 7
        assert step_match_seq([3, 7], None, 'newer') == 3

    def test_no_matches(self):
        assert step_match_seq([], 5, 'older') is None


class TestMatchPositionAndStatus:
    def test_position_is_one_based_oldest_first(self):
        assert match_position([3, 7, 12], 3) == 1
        assert match_position([3, 7, 12], 12) == 3

    def test_absent_is_none(self):
        assert match_position([3, 7, 12], 5) is None
        assert match_position([3, 7, 12], None) is None
        assert match_position([], 5) is None

    def test_status_text(self):
        assert format_find_status('timeout', 3, 17) == 'find "timeout"  3/17'
        assert format_find_status('timeout', None, 17) == 'find "timeout"  -/17'


class TestRowsMeta:
    def test_aligns_with_ring_visible_rows(self):
        ring = RingLog(maxlen=100)
        ring.set_width(4)
        for text in ('aaaaaaaaa', 'bb', 'cccccc', 'd'):  # 3, 1, 2, 1 rows
            ring.append([(text, None, None, False)], text)
        entries = ring.visible_entries()
        for view_offset in range(0, 7):
            for height in range(0, 8):
                rows = ring.visible_rows(view_offset, height)
                meta = rows_meta(entries, view_offset, height)
                assert len(meta) == len(rows)
                for (segments, _), (seq, row_in_line) in zip(rows, meta):
                    plain = entries[seq][2]
                    row_text = ''.join(s[0] for s in segments)
                    assert row_text == plain[row_in_line * 4:row_in_line * 4 + 4]

    def test_respects_focus_filter(self):
        ring = RingLog(maxlen=100)
        ring.set_width(80)
        for text in ('keep 0', 'drop 1', 'keep 2'):
            ring.append([(text, None, None, False)], text)
        ring.set_filter(lambda plain, n, l: plain.startswith('keep'))
        meta = rows_meta(ring.visible_entries(), 0, 5)
        assert meta == [(0, 0), (2, 0)]


class TestRowHighlightSpans:
    def test_match_within_one_row(self):
        assert row_highlight_spans('hello timeout', 'timeout', 0, 80, 13) == [(6, 12)]

    def test_match_split_across_wrap_boundary(self):
        # width 8: row 0 = "abc time", row 1 = "out xyz"
        plain = 'abc timeout xyz'
        assert row_highlight_spans(plain, 'timeout', 0, 8, 8) == [(4, 7)]
        assert row_highlight_spans(plain, 'timeout', 1, 8, 7) == [(0, 2)]

    def test_match_on_another_row_not_reported(self):
        plain = 'timeout and more text'
        assert row_highlight_spans(plain, 'timeout', 1, 8, 8) == []
