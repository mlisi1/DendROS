"""Tests for lib/tui_pure.py — the pure/testable layer backing the TUI launch mode.

The curses-owning layer (lib/launch_tui.py's run_tui/_tui_main) needs a real controlling
terminal and is manual-testing only, same accepted gap as dendros_config.py's own curses
interaction. These tests cover: ANSI SGR parsing, 256-color quantization, PairCache
allocation/eviction (via a fake curses double), RingLog's on-demand wrap/scrollback
behavior, selection math, and mouse/keyboard escape-sequence decoding — no real curses or
threads involved.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from lib.tui_pure import (
    quantize_rgb_to_256,
    segments_from_ansi,
    wrap_line,
    selection_span_for_row,
    extract_selection_text,
    build_osc52_sequence,
    screen_row_to_tail_offset,
    compute_scrollbar_thumb,
    decode_sgr_mouse,
    decode_navigation_key,
    find_clipboard_tool,
    copy_via_system_clipboard_tool,
    PairCache,
    RingLog,
)
import base64
import lib.crash_alert as ca


# ── quantize_rgb_to_256 ────────────────────────────────────────────────────────

class TestQuantizeRgbTo256:
    def test_black(self):
        assert quantize_rgb_to_256(0, 0, 0) == 16

    def test_white(self):
        assert quantize_rgb_to_256(255, 255, 255) == 231

    def test_pure_red(self):
        assert quantize_rgb_to_256(255, 0, 0) == 16 + 36 * 5

    def test_pure_green(self):
        assert quantize_rgb_to_256(0, 255, 0) == 16 + 6 * 5

    def test_pure_blue(self):
        assert quantize_rgb_to_256(0, 0, 255) == 16 + 5

    def test_in_range(self):
        for r, g, b in [(0, 75, 107), (224, 127, 0), (128, 64, 200), (1, 254, 3)]:
            idx = quantize_rgb_to_256(r, g, b)
            assert 16 <= idx <= 231

    def test_clamps_out_of_range_input(self):
        assert quantize_rgb_to_256(-10, 300, 128) == quantize_rgb_to_256(0, 255, 128)

    def test_dark_grey_maps_to_grayscale_ramp_not_a_hued_cube_color(self):
        # Regression: naive linear-rounding to 6 cube steps picked cube level 1 (value 95,
        # a distinctly blue-tinted color) for a neutral dark grey like (24, 24, 26) instead
        # of the much closer grayscale-ramp entry — the header background bug this caught.
        idx = quantize_rgb_to_256(24, 24, 26)
        assert 232 <= idx <= 255, f"expected a grayscale-ramp index, got {idx}"

    def test_mid_grey_maps_to_grayscale_ramp(self):
        idx = quantize_rgb_to_256(128, 128, 130)
        assert 232 <= idx <= 255

    def test_saturated_colors_still_use_cube_not_grayscale(self):
        for r, g, b in [(224, 127, 0), (0, 75, 107), (255, 0, 0)]:
            idx = quantize_rgb_to_256(r, g, b)
            assert 16 <= idx <= 231, f"expected a cube index for a saturated color, got {idx}"

    def test_cube_uses_real_xterm_levels_not_linear_steps(self):
        # A value roughly midway between cube levels 0 (0) and 1 (95) should NOT round up
        # to level 1 just because naive linear rounding (round(v/255*5)) would put it in
        # the "second sixth" of the 0-255 range.
        idx = quantize_rgb_to_256(30, 30, 30)
        # 30 is much closer to grayscale ramp (nearest ~28) than to cube level 0 (0) or
        # level 1 (95) -- either way it must not silently become a saturated color.
        assert idx != (16 + 36 * 1 + 6 * 1 + 1)  # would be the wrong naive "level 1" cube cell


# ── segments_from_ansi ──────────────────────────────────────────────────────────

class TestSegmentsFromAnsi:
    def test_plain_text_no_ansi(self):
        segs = segments_from_ansi("hello world")
        assert segs == [("hello world", None, None, False)]

    def test_empty_string(self):
        assert segments_from_ansi("") == []

    def test_truecolor_fg_quantized(self):
        line = "\033[38;2;255;0;0mred\033[0m"
        segs = segments_from_ansi(line)
        assert len(segs) == 1
        text, fg, bg, bold = segs[0]
        assert text == "red"
        assert fg == quantize_rgb_to_256(255, 0, 0)
        assert bg is None
        assert bold is False

    def test_bold_truecolor_combo(self):
        line = "\033[1;38;2;0;75;107mblue\033[0m"
        segs = segments_from_ansi(line)
        text, fg, bg, bold = segs[0]
        assert text == "blue"
        assert bold is True
        assert fg == quantize_rgb_to_256(0, 75, 107)

    def test_reset_clears_state(self):
        line = "\033[1;31mred\033[0mplain"
        segs = segments_from_ansi(line)
        assert segs[0] == ("red", 31 - 30, None, True)
        assert segs[1] == ("plain", None, None, False)

    def test_standard_fg_color(self):
        segs = segments_from_ansi("\033[34mtext\033[0m")
        assert segs[0][1] == 34 - 30  # blue -> index 4

    def test_bright_fg_color(self):
        segs = segments_from_ansi("\033[92mtext\033[0m")
        assert segs[0][1] == (92 - 90) + 8

    def test_standard_bg_color(self):
        segs = segments_from_ansi("\033[41mtext\033[0m")
        assert segs[0][2] == 41 - 40

    def test_bright_bg_color(self):
        segs = segments_from_ansi("\033[101mtext\033[0m")
        assert segs[0][2] == (101 - 100) + 8

    def test_bg_truecolor_quantized(self):
        line = "\033[48;2;255;255;255mtext\033[0m"
        segs = segments_from_ansi(line)
        assert segs[0][2] == quantize_rgb_to_256(255, 255, 255)

    def test_multiple_runs(self):
        line = "\033[31ma\033[0m \033[32mb\033[0m"
        segs = segments_from_ansi(line)
        texts = [s[0] for s in segs]
        assert texts == ["a", " ", "b"]

    def test_erase_to_eol_stripped_not_literal(self):
        # param_watcher's inverted style ends lines with '\033[K' (erase-to-EOL) to pad
        # the background — not an SGR color code, so it must be stripped rather than
        # showing up as literal garbage text (this was a real bug: '^[[K' appeared
        # visibly at the end of param-change notifications in the TUI).
        line = "\033[107;30m value \033[K\033[0m"
        segs = segments_from_ansi(line)
        combined = ''.join(s[0] for s in segs)
        assert '\033[K' not in combined
        assert 'K' not in combined.replace(' value ', '')

    def test_erase_to_eol_does_not_disturb_surrounding_color(self):
        line = "\033[31mred\033[K\033[0m plain"
        segs = segments_from_ansi(line)
        assert segs[0] == ("red", 31 - 30, None, False)
        assert segs[1] == (" plain", None, None, False)

    def test_dendros_tag_split(self):
        # Same shape as lib.colors.DENDROS_TAG: two colored runs, no plain text between.
        line = '\033[38;2;0;75;107;1m[dend\033[38;2;224;127;0;1mROS]\033[0m'
        segs = segments_from_ansi(line)
        assert [s[0] for s in segs] == ['[dend', 'ROS]']
        assert segs[0][1] == quantize_rgb_to_256(0, 75, 107)
        assert segs[1][1] == quantize_rgb_to_256(224, 127, 0)
        assert segs[0][3] is True and segs[1][3] is True

    def test_256_direct_code(self):
        segs = segments_from_ansi("\033[38;5;196mtext\033[0m")
        assert segs[0][1] == 196

    def test_reverse_video_swaps_fg_into_bg(self):
        # tag_style: inverted -> colorizers.py emits ansi_code + ';7' (e.g. "34;7").
        # DendROS's inverted convention is colored bg + black hollow text (matching
        # param_watcher's _fg_to_bg-built inverted style), not curses' "default" fg.
        segs = segments_from_ansi("\033[34;7m[TAG]\033[0m")
        text, fg, bg, bold = segs[0]
        assert text == "[TAG]"
        assert fg == 0  # explicit black, not None/default
        assert bg == 34 - 30

    def test_reverse_video_with_truecolor_and_bold(self):
        line = "\033[38;2;0;75;107;1;7m[LOC]\033[0m"
        segs = segments_from_ansi(line)
        text, fg, bg, bold = segs[0]
        assert fg == 0
        assert bg == quantize_rgb_to_256(0, 75, 107)
        assert bold is True

    def test_fg_reset_39(self):
        segs = segments_from_ansi("\033[31mred\033[39mplain\033[0m")
        assert segs[0][1] == 1
        assert segs[1][1] is None


# ── PairCache ──────────────────────────────────────────────────────────────────

class FakeCurses:
    """Minimal curses double: just what PairCache actually touches."""

    def __init__(self, color_pairs=8):
        self.COLOR_PAIRS = color_pairs
        self.A_BOLD = 1 << 20
        self.init_pair_calls = []

    def init_pair(self, n, fg, bg):
        self.init_pair_calls.append((n, fg, bg))

    def color_pair(self, n):
        return n * 1000  # sentinel encoding so tests can assert which pair was used


class TestPairCache:
    def test_first_allocation(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        pair = cache.get_pair(1, -1)
        assert pair >= 1
        assert fc.init_pair_calls == [(pair, 1, -1)]

    def test_same_color_reuses_pair(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        p1 = cache.get_pair(5, -1)
        p2 = cache.get_pair(5, -1)
        assert p1 == p2
        assert len(fc.init_pair_calls) == 1

    def test_distinct_colors_get_distinct_pairs(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        p1 = cache.get_pair(1, -1)
        p2 = cache.get_pair(2, -1)
        assert p1 != p2

    def test_eviction_when_capacity_exhausted(self):
        fc = FakeCurses(color_pairs=3)  # capacity = COLOR_PAIRS - 1 = 2
        cache = PairCache(fc)
        cache.get_pair(1, -1)
        cache.get_pair(2, -1)
        # capacity exhausted: allocating a 3rd distinct color must evict the LRU (color 1)
        cache.get_pair(3, -1)
        assert (1, -1) not in cache._pairs
        assert (2, -1) in cache._pairs
        assert (3, -1) in cache._pairs

    def test_recently_used_color_survives_eviction(self):
        fc = FakeCurses(color_pairs=3)
        cache = PairCache(fc)
        cache.get_pair(1, -1)
        cache.get_pair(2, -1)
        cache.get_pair(1, -1)  # touch color 1 again -> now LRU is color 2
        cache.get_pair(3, -1)
        assert (2, -1) not in cache._pairs
        assert (1, -1) in cache._pairs

    def test_explicit_max_pairs_overrides_curses_color_pairs(self):
        fc = FakeCurses(color_pairs=1000)
        cache = PairCache(fc, max_pairs=1)
        cache.get_pair(1, -1)
        cache.get_pair(2, -1)  # must evict immediately since capacity is 1
        assert len(cache._pairs) == 1

    def test_attr_for_applies_bold(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        attr = cache.attr_for(fg=1, bg=None, bold=True)
        assert attr & fc.A_BOLD

    def test_attr_for_no_bold(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        attr = cache.attr_for(fg=1, bg=None, bold=False)
        assert not (attr & fc.A_BOLD)

    def test_attr_for_encodes_pair(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        pair = cache.get_pair(7, -1)
        attr = cache.attr_for(fg=7, bg=None, bold=False)
        assert attr == fc.color_pair(pair)


# ── wrap_line ────────────────────────────────────────────────────────────────

class TestWrapLine:
    def test_short_line_is_one_row(self):
        rows = wrap_line([("hello", None, None, False)], 20)
        assert rows == [[("hello", None, None, False)]]

    def test_exact_width_line_is_one_row_no_phantom_row(self):
        rows = wrap_line([("abcde", None, None, False)], 5)
        assert rows == [[("abcde", None, None, False)]]

    def test_one_char_over_width_wraps_to_two_rows(self):
        rows = wrap_line([("abcdef", None, None, False)], 5)
        assert rows == [[("abcde", None, None, False)], [("f", None, None, False)]]

    def test_color_preserved_across_wrap_boundary(self):
        rows = wrap_line([("abc", 1, None, False), ("defgh", 2, None, False)], 5)
        assert rows == [
            [("abc", 1, None, False), ("de", 2, None, False)],
            [("fgh", 2, None, False)],
        ]

    def test_empty_line_yields_one_empty_row(self):
        assert wrap_line([], 10) == [[]]

    def test_non_positive_width_is_guarded_not_infinite(self):
        rows = wrap_line([("ab", None, None, False)], 0)
        # guarded to width=1 -- must terminate and split one char per row
        assert rows == [[("a", None, None, False)], [("b", None, None, False)]]

    def test_multiple_lines_worth_of_wraps(self):
        rows = wrap_line([("0123456789", None, None, False)], 3)
        assert [r[0][0] for r in rows] == ["012", "345", "678", "9"]


# ── RingLog ──────────────────────────────────────────────────────────────────

class TestRingLog:
    def test_bounded_length(self):
        ring = RingLog(maxlen=3)
        for i in range(5):
            ring.append([(str(i), None, None, False)], str(i))
        assert len(ring) == 3
        assert ring.plain_lines() == ['2', '3', '4']

    def test_plain_lines_aligned_with_segments(self):
        ring = RingLog(maxlen=10)
        ring.append([("a", None, None, False)], "a")
        ring.append([("b", None, None, False)], "b")
        assert ring.plain_lines() == ["a", "b"]
        assert ring[0][0] == [("a", None, None, False)]

    def test_append_without_width_set_does_not_crash(self):
        ring = RingLog(maxlen=5)
        ring.append([("x", None, None, False)], "x")  # set_width() never called
        assert len(ring) == 1

    # ── set_width() / total_rows() ───────────────────────────────────────────

    def test_total_rows_matches_line_count_when_nothing_wraps(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        for i in range(3):
            ring.append([(f"line{i}", None, None, False)], f"line{i}")
        assert ring.total_rows() == 3

    def test_total_rows_counts_wrapped_rows(self):
        ring = RingLog(maxlen=100)
        ring.set_width(5)
        ring.append([("abcdefghij", None, None, False)], "abcdefghij")  # 10 chars / 5 = 2 rows
        assert ring.total_rows() == 2

    def test_set_width_is_a_noop_when_unchanged(self):
        ring = RingLog(maxlen=100)
        ring.set_width(10)
        ring.append([("hello world", None, None, False)], "hello world")
        before = ring.total_rows()
        ring.set_width(10)  # same width again
        assert ring.total_rows() == before

    def test_set_width_reflows_existing_history(self):
        ring = RingLog(maxlen=100)
        ring.set_width(5)
        ring.append([("abcdefghij", None, None, False)], "abcdefghij")
        assert ring.total_rows() == 2  # wraps at width 5
        ring.set_width(40)
        assert ring.total_rows() == 1  # fits on one row at width 40

    def test_append_after_width_set_updates_total_incrementally(self):
        ring = RingLog(maxlen=100)
        ring.set_width(5)
        ring.append([("abcde", None, None, False)], "abcde")  # 1 row
        ring.append([("abcdefghij", None, None, False)], "abcdefghij")  # 2 rows
        assert ring.total_rows() == 3

    def test_eviction_reduces_total_rows_by_evicted_line(self):
        ring = RingLog(maxlen=2)
        ring.set_width(5)
        ring.append([("abcdefghij", None, None, False)], "abcdefghij")  # 2 rows, will be evicted
        ring.append([("short", None, None, False)], "short")  # 1 row
        assert ring.total_rows() == 3
        ring.append([("x", None, None, False)], "x")  # 1 row -- evicts the first (2-row) line
        assert len(ring) == 2
        assert ring.total_rows() == 2  # "short" (1) + "x" (1), the 2-row line is gone

    # ── visible_rows() ────────────────────────────────────────────────────────

    @staticmethod
    def _texts(rows):
        return [''.join(seg[0] for seg in segments) for segments, _ in rows]

    def test_visible_rows_tail_window_single_row_lines(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        for i in range(5):
            ring.append([(f"line{i}", None, None, False)], f"line{i}")
        rows = ring.visible_rows(0, 2)
        assert self._texts(rows) == ["line3", "line4"]

    def test_visible_rows_spans_a_wrapped_multi_row_line(self):
        ring = RingLog(maxlen=100)
        ring.set_width(5)
        ring.append([("a", None, None, False)], "a")
        ring.append([("bcdefghij", None, None, False)], "bcdefghij")  # wraps to 2 rows: "bcdef","ghij"
        ring.append([("k", None, None, False)], "k")
        rows = ring.visible_rows(0, 3)
        assert self._texts(rows) == ["bcdef", "ghij", "k"]

    def test_visible_rows_scrolled_back(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        for i in range(5):
            ring.append([(f"line{i}", None, None, False)], f"line{i}")
        rows = ring.visible_rows(2, 2)  # 2 rows back from the tail, 2 rows tall
        assert self._texts(rows) == ["line1", "line2"]

    def test_visible_rows_near_start_of_short_history(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        ring.append([("only", None, None, False)], "only")
        rows = ring.visible_rows(0, 5)  # asking for more rows than exist
        assert self._texts(rows) == ["only"]

    def test_visible_rows_empty_history(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        assert ring.visible_rows(0, 5) == []

    def test_visible_rows_is_continuation_flags_wrap_boundaries(self):
        ring = RingLog(maxlen=100)
        ring.set_width(5)
        ring.append([("a", None, None, False)], "a")  # 1 row: not a continuation
        ring.append([("bcdefghij", None, None, False)], "bcdefghij")  # 2 rows: "bcdef","ghij"
        ring.append([("k", None, None, False)], "k")  # 1 row: not a continuation
        rows = ring.visible_rows(0, 4)
        flags = [is_cont for _, is_cont in rows]
        assert flags == [False, False, True, False]

    def test_visible_rows_arbitrary_historical_range(self):
        # visible_rows() is also used to fetch a range that isn't the live viewport at
        # all (e.g. a yank spanning an old selection) — view_offset=min(a,b),
        # height=abs(a-b)+1 should return exactly the rows between two tail offsets.
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        for i in range(5):
            ring.append([(f"line{i}", None, None, False)], f"line{i}")
        # offsets: line4=0, line3=1, line2=2, line1=3, line0=4
        rows = ring.visible_rows(1, 3 - 1 + 1)  # range from offset 1 (line3) to offset 3 (line1)
        assert self._texts(rows) == ["line1", "line2", "line3"]


# ── crash_alert.set_sink() — TUI banner redirection ─────────────────────────────

class TestCrashAlertSink:
    def setup_method(self):
        ca.setup(enabled=True, color='node', interval=30)
        ca._dead_nodes = []
        ca._death_counts = {}
        ca.set_sink(None)

    def teardown_method(self):
        ca.set_sink(None)

    def test_default_sink_is_none(self):
        ca.set_sink(None)
        assert ca._sink is None

    def test_set_sink_redirects_banner(self, capsys):
        captured = []
        ca.set_sink(lambda text: captured.append(text))
        ca.record_death('talker', '1', None)
        ca.print_alert_banner()
        assert len(captured) == 1
        assert 'talker' in captured[0]
        out, _ = capsys.readouterr()
        assert out == ''  # nothing went to stdout while a sink is set

    def test_no_sink_falls_back_to_stdout(self, capsys):
        ca.set_sink(None)
        ca.record_death('talker', '1', None)
        ca.print_alert_banner()
        out, _ = capsys.readouterr()
        assert 'talker' in out

    def test_sink_receives_no_trailing_newline(self):
        captured = []
        ca.set_sink(lambda text: captured.append(text))
        ca.record_death('talker', '1', None)
        ca.print_alert_banner()
        assert not captured[0].endswith('\n')


# ── text-selection logic (selection_span_for_row / extract_selection_text) ──────────

class TestSelectionSpanForRow:
    def test_no_anchor_means_no_selection(self):
        assert selection_span_for_row(0, 10, None, (0, 0)) is None

    def test_single_row_selection_span_is_inclusive(self):
        # anchor and cursor on the same row (offset 0), cursor ahead of anchor
        span = selection_span_for_row(0, 10, anchor=(0, 2), cursor=(0, 5))
        assert span == (2, 5)

    def test_single_row_selection_is_order_independent(self):
        forward = selection_span_for_row(0, 10, anchor=(0, 2), cursor=(0, 5))
        backward = selection_span_for_row(0, 10, anchor=(0, 5), cursor=(0, 2))
        assert forward == backward == (2, 5)

    def test_row_outside_range_is_not_selected(self):
        # selection spans offsets 0..2; offset 5 is untouched
        assert selection_span_for_row(5, 10, anchor=(2, 0), cursor=(0, 0)) is None

    def test_older_endpoint_row_selected_from_its_column_to_end(self):
        # anchor is the older (higher-offset) endpoint at col 3; that row should be
        # selected from col 3 to the end of the row.
        span = selection_span_for_row(2, 10, anchor=(2, 3), cursor=(0, 1))
        assert span == (3, 9)

    def test_newer_endpoint_row_selected_from_start_to_its_column(self):
        span = selection_span_for_row(0, 10, anchor=(2, 3), cursor=(0, 1))
        assert span == (0, 1)

    def test_middle_row_is_selected_whole(self):
        span = selection_span_for_row(1, 10, anchor=(2, 3), cursor=(0, 1))
        assert span == (0, 9)

    def test_order_independence_for_multi_row_selection(self):
        # swapping which endpoint is "anchor" vs "cursor" must not change the result
        a = selection_span_for_row(2, 10, anchor=(2, 3), cursor=(0, 1))
        b = selection_span_for_row(2, 10, anchor=(0, 1), cursor=(2, 3))
        assert a == b == (3, 9)


class TestExtractSelectionText:
    def _row(self, text, is_continuation=False):
        return ([(text, None, None, False)], is_continuation)

    def test_no_anchor_returns_empty(self):
        assert extract_selection_text([self._row("hello")], None, (0, 0)) == ''

    def test_no_rows_returns_empty(self):
        assert extract_selection_text([], (0, 0), (0, 3)) == ''

    def test_single_row_slice_is_inclusive(self):
        rows = [self._row("hello world")]
        text = extract_selection_text(rows, anchor=(0, 0), cursor=(0, 4))
        assert text == "hello"

    def test_multi_row_distinct_lines_get_real_newline(self):
        rows = [self._row("first"), self._row("second")]
        # anchor at start of "first" (offset 1, the older row), cursor at end of
        # "second" (offset 0, the newer row) -- both rows taken whole here.
        text = extract_selection_text(rows, anchor=(1, 0), cursor=(0, 5))
        assert text == "first\nsecond"

    def test_wrap_continuation_gets_no_separator(self):
        # "second" here is a wrap continuation of "first" -- one flowed logical line,
        # should join with no newline in between.
        rows = [self._row("first"), self._row("second", is_continuation=True)]
        text = extract_selection_text(rows, anchor=(1, 0), cursor=(0, 5))
        assert text == "firstsecond"

    def test_trims_first_and_last_row_to_selection_columns(self):
        rows = [self._row("abcdef"), self._row("ghijkl"), self._row("mnopqr")]
        # anchor on the oldest row (offset 2) at col 3 -> "def"; cursor on the newest
        # row (offset 0) at col 2 -> "mno"; middle row taken whole.
        text = extract_selection_text(rows, anchor=(2, 3), cursor=(0, 2))
        assert text == "def\nghijkl\nmno"


class TestBuildOsc52Sequence:
    def test_wraps_base64_payload_in_osc52_escape(self):
        seq = build_osc52_sequence("hello")
        assert seq.startswith(b'\033]52;c;')
        assert seq.endswith(b'\a')

    def test_payload_round_trips_through_base64(self):
        seq = build_osc52_sequence("hello world")
        b64 = seq[len(b'\033]52;c;'):-1]
        assert base64.b64decode(b64) == b"hello world"

    def test_unicode_round_trips_as_utf8(self):
        seq = build_osc52_sequence("café")
        b64 = seq[len(b'\033]52;c;'):-1]
        assert base64.b64decode(b64) == "café".encode('utf-8')

    def test_truncates_past_max_bytes(self):
        seq = build_osc52_sequence("abcdefghij", max_bytes=5)
        b64 = seq[len(b'\033]52;c;'):-1]
        assert base64.b64decode(b64) == b"abcde"


# ── find_clipboard_tool / copy_via_system_clipboard_tool ──────────────────────────

class TestFindClipboardTool:
    def test_none_found_returns_none(self):
        assert find_clipboard_tool(which_fn=lambda name: None) is None

    def test_first_available_tool_wins(self):
        # xclip is tried before xsel/wl-copy -- even if a later one would also be found,
        # the first match in priority order should be returned.
        found = {'xclip', 'xsel', 'wl-copy'}
        cmd = find_clipboard_tool(which_fn=lambda name: f'/usr/bin/{name}' if name in found else None)
        assert cmd[0] == 'xclip'

    def test_falls_through_to_second_tool_when_first_missing(self):
        cmd = find_clipboard_tool(which_fn=lambda name: '/usr/bin/xsel' if name == 'xsel' else None)
        assert cmd[0] == 'xsel'

    def test_falls_through_to_third_tool(self):
        cmd = find_clipboard_tool(which_fn=lambda name: '/usr/bin/wl-copy' if name == 'wl-copy' else None)
        assert cmd[0] == 'wl-copy'


class TestCopyViaSystemClipboardTool:
    def test_returns_false_when_no_tool_found(self):
        calls = []
        result = copy_via_system_clipboard_tool(
            "hello", which_fn=lambda name: None, run_fn=lambda *a, **k: calls.append((a, k)))
        assert result is False
        assert calls == []

    def test_runs_found_tool_with_text_as_stdin(self):
        calls = []
        result = copy_via_system_clipboard_tool(
            "hello world",
            which_fn=lambda name: f'/usr/bin/{name}' if name == 'xclip' else None,
            run_fn=lambda *a, **k: calls.append((a, k)))
        assert result is True
        assert len(calls) == 1
        (cmd,), kwargs = calls[0]
        assert cmd[0] == 'xclip'
        assert kwargs['input'] == b'hello world'

    def test_run_exception_is_swallowed_and_still_returns_true(self):
        def raising_run(*a, **k):
            raise OSError("no DISPLAY")
        result = copy_via_system_clipboard_tool(
            "hello", which_fn=lambda name: '/usr/bin/xclip' if name == 'xclip' else None,
            run_fn=raising_run)
        assert result is True  # a tool was found and an attempt was made


# ── screen_row_to_tail_offset ────────────────────────────────────────────────────

class TestScreenRowToTailOffset:
    def test_top_row_of_full_viewport_is_the_oldest_offset(self):
        # n_rows=5, view_offset=0: body_row 0 (top) is the oldest of the 5 visible rows.
        assert screen_row_to_tail_offset(0, 5, 0) == 4

    def test_bottom_row_of_full_viewport_is_the_newest_offset(self):
        assert screen_row_to_tail_offset(4, 5, 0) == 0

    def test_middle_row(self):
        assert screen_row_to_tail_offset(2, 5, 0) == 2

    def test_scrolled_back_view_offset_shifts_every_row_older(self):
        # Scrolled back 3 rows: the same body_row now maps to an offset 3 further back.
        assert screen_row_to_tail_offset(4, 5, 3) == 3
        assert screen_row_to_tail_offset(0, 5, 3) == 7

    def test_negative_body_row_is_out_of_range(self):
        assert screen_row_to_tail_offset(-1, 5, 0) is None

    def test_body_row_at_or_past_n_rows_is_out_of_range(self):
        assert screen_row_to_tail_offset(5, 5, 0) is None
        assert screen_row_to_tail_offset(10, 5, 0) is None


# ── compute_scrollbar_thumb ────────────────────────────────────────────────────────

class TestComputeScrollbarThumb:
    def test_nothing_to_scroll_no_thumb(self):
        # max_offset <= 0 -- everything fits, no thumb, just an empty track.
        assert compute_scrollbar_thumb(20, 0, 0, 15) == (0, 0)

    def test_total_rows_not_exceeding_track_height_no_thumb(self):
        assert compute_scrollbar_thumb(20, 0, 0, 20) == (0, 0)

    def test_zero_track_height(self):
        assert compute_scrollbar_thumb(0, 0, 0, 100) == (0, 0)

    def test_at_tail_thumb_sits_at_bottom(self):
        # view_offset=0 (following the tail) -> thumb should be at the bottom of the track.
        start, height = compute_scrollbar_thumb(10, 0, 90, 100)
        assert start + height == 10  # flush with the bottom edge

    def test_fully_scrolled_back_thumb_sits_at_top(self):
        start, height = compute_scrollbar_thumb(10, 90, 90, 100)
        assert start == 0  # flush with the top edge

    def test_midpoint_thumb_is_roughly_centered(self):
        start, height = compute_scrollbar_thumb(10, 45, 90, 100)
        # Not pinned to either edge.
        assert start > 0
        assert start + height < 10

    def test_thumb_height_proportional_to_visible_fraction(self):
        # Viewport shows track_height (10) rows out of 20 total -> half visible -> thumb
        # roughly half the track.
        _, height = compute_scrollbar_thumb(10, 0, 10, 20)
        assert height == 5

    def test_thumb_height_at_least_one_for_huge_scrollback(self):
        _, height = compute_scrollbar_thumb(10, 0, 999990, 1000000)
        assert height >= 1

    def test_thumb_height_never_exceeds_track_height(self):
        _, height = compute_scrollbar_thumb(10, 0, 1, 11)
        assert height <= 10

    def test_out_of_range_view_offset_is_clamped(self):
        # view_offset beyond max_offset shouldn't push the thumb past the top.
        start, _ = compute_scrollbar_thumb(10, 999, 90, 100)
        assert start == 0


# ── decode_sgr_mouse ──────────────────────────────────────────────────────────────

class TestDecodeSgrMouse:
    def test_left_button_press(self):
        ev = decode_sgr_mouse(0, 10, 5, 'M')
        assert ev == {
            'button': 0, 'is_motion': False, 'is_wheel': False, 'is_release': False,
            'wheel_dir': None, 'col': 9, 'row': 4,
        }

    def test_release_terminator_sets_is_release(self):
        ev = decode_sgr_mouse(0, 1, 1, 'm')
        assert ev['is_release'] is True

    def test_press_terminator_is_not_release(self):
        ev = decode_sgr_mouse(0, 1, 1, 'M')
        assert ev['is_release'] is False

    def test_motion_flag_bit_32(self):
        # Cb=32 -> button 0 (left) + motion bit set, no wheel.
        ev = decode_sgr_mouse(32, 1, 1, 'M')
        assert ev['is_motion'] is True
        assert ev['button'] == 0
        assert ev['is_wheel'] is False

    def test_plain_press_has_no_motion_flag(self):
        ev = decode_sgr_mouse(0, 1, 1, 'M')
        assert ev['is_motion'] is False

    def test_wheel_up(self):
        ev = decode_sgr_mouse(64, 1, 1, 'M')
        assert ev['is_wheel'] is True
        assert ev['wheel_dir'] == 'up'

    def test_wheel_down(self):
        ev = decode_sgr_mouse(65, 1, 1, 'M')
        assert ev['is_wheel'] is True
        assert ev['wheel_dir'] == 'down'

    def test_non_wheel_event_has_no_wheel_dir(self):
        ev = decode_sgr_mouse(1, 1, 1, 'M')  # middle-button press
        assert ev['wheel_dir'] is None

    def test_button_codes(self):
        assert decode_sgr_mouse(0, 1, 1, 'M')['button'] == 0  # left
        assert decode_sgr_mouse(1, 1, 1, 'M')['button'] == 1  # middle
        assert decode_sgr_mouse(2, 1, 1, 'M')['button'] == 2  # right

    def test_coordinates_convert_1_based_to_0_based(self):
        ev = decode_sgr_mouse(0, 1, 1, 'M')
        assert ev['col'] == 0
        assert ev['row'] == 0

    def test_modifier_bits_do_not_corrupt_button_or_motion_decode(self):
        # Shift (4) + left-button motion (32) held together: modifier bits are ignored,
        # not accidentally interpreted as part of the button/motion/wheel encoding.
        ev = decode_sgr_mouse(32 | 4, 1, 1, 'M')
        assert ev['button'] == 0
        assert ev['is_motion'] is True
        assert ev['is_wheel'] is False

    def test_modifier_bits_do_not_corrupt_wheel_decode(self):
        ev = decode_sgr_mouse(64 | 8, 1, 1, 'M')  # wheel-up + Meta
        assert ev['is_wheel'] is True
        assert ev['wheel_dir'] == 'up'


# ── decode_navigation_key ─────────────────────────────────────────────────────────

class TestDecodeNavigationKey:
    def test_letter_forms(self):
        assert decode_navigation_key('A') == 'up'
        assert decode_navigation_key('B') == 'down'
        assert decode_navigation_key('C') == 'right'
        assert decode_navigation_key('D') == 'left'
        assert decode_navigation_key('H') == 'home'
        assert decode_navigation_key('F') == 'end'

    def test_unrecognized_letter_is_none(self):
        assert decode_navigation_key('Z') is None

    def test_tilde_forms(self):
        assert decode_navigation_key('~', '5') == 'page_up'
        assert decode_navigation_key('~', '6') == 'page_down'
        assert decode_navigation_key('~', '1') == 'home'
        assert decode_navigation_key('~', '7') == 'home'
        assert decode_navigation_key('~', '4') == 'end'
        assert decode_navigation_key('~', '8') == 'end'

    def test_unrecognized_tilde_digits_is_none(self):
        assert decode_navigation_key('~', '99') is None

    def test_letter_form_with_digits_is_none(self):
        # A letter final byte should never be paired with a nonempty digit string --
        # the two encodings are mutually exclusive.
        assert decode_navigation_key('A', '5') is None
