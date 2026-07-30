"""Tests for lib/launch_tui.py — the pure/testable layer only.

The curses-owning layer (run_tui/_tui_main) needs a real controlling terminal and is
manual-testing only, same accepted gap as dendros_config.py's own curses interaction.
These tests cover: ANSI SGR parsing, 256-color quantization, PairCache allocation/eviction
(via a fake curses double), and RingLog's ring-buffer + pad-projection behavior (via a fake
pad double) — no real curses or threads involved.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from lib.launch_tui import (
    quantize_rgb_to_256,
    segments_from_ansi,
    wrap_line,
    PairCache,
    RingLog,
)
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

    def test_visible_rows_tail_window_single_row_lines(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        for i in range(5):
            ring.append([(f"line{i}", None, None, False)], f"line{i}")
        rows = ring.visible_rows(0, 2)
        assert [r[0][0] for r in rows] == ["line3", "line4"]

    def test_visible_rows_spans_a_wrapped_multi_row_line(self):
        ring = RingLog(maxlen=100)
        ring.set_width(5)
        ring.append([("a", None, None, False)], "a")
        ring.append([("bcdefghij", None, None, False)], "bcdefghij")  # wraps to 2 rows: "bcdef","ghij"
        ring.append([("k", None, None, False)], "k")
        rows = ring.visible_rows(0, 3)
        assert [r[0][0] for r in rows] == ["bcdef", "ghij", "k"]

    def test_visible_rows_scrolled_back(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        for i in range(5):
            ring.append([(f"line{i}", None, None, False)], f"line{i}")
        rows = ring.visible_rows(2, 2)  # 2 rows back from the tail, 2 rows tall
        assert [r[0][0] for r in rows] == ["line1", "line2"]

    def test_visible_rows_near_start_of_short_history(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        ring.append([("only", None, None, False)], "only")
        rows = ring.visible_rows(0, 5)  # asking for more rows than exist
        assert [r[0][0] for r in rows] == ["only"]

    def test_visible_rows_empty_history(self):
        ring = RingLog(maxlen=100)
        ring.set_width(40)
        assert ring.visible_rows(0, 5) == []


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
