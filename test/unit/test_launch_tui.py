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


# ── RingLog ──────────────────────────────────────────────────────────────────

class FakePad:
    """Minimal curses pad double: just what RingLog._render_last actually touches."""

    def __init__(self, height=5, width=40):
        self.height = height
        self.width = width
        self.scroll_calls = 0
        self.addstr_calls = []  # (row, col, text, attr)
        self.rows = [''] * height

    def getmaxyx(self):
        return (self.height, self.width)

    def scroll(self, n):
        self.scroll_calls += n
        self.rows.pop(0)
        self.rows.append('')

    def move(self, row, col):
        pass

    def clrtoeol(self):
        pass

    def addstr(self, row, col, text, attr=0):
        self.addstr_calls.append((row, col, text, attr))
        line = self.rows[row]
        line = line.ljust(col) + text
        self.rows[row] = line


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

    def test_append_without_pad_does_not_crash(self):
        ring = RingLog(maxlen=5)
        ring.append([("x", None, None, False)], "x")  # no pad attached
        assert len(ring) == 1

    def test_append_scrolls_pad_once_per_line(self):
        pad = FakePad(height=5, width=40)
        ring = RingLog(maxlen=100, pad=pad)
        ring.append([("first", None, None, False)], "first")
        ring.append([("second", None, None, False)], "second")
        assert pad.scroll_calls == 2

    def test_append_writes_to_last_row(self):
        pad = FakePad(height=5, width=40)
        ring = RingLog(maxlen=100, pad=pad)
        ring.append([("hello", None, None, False)], "hello")
        assert pad.addstr_calls[-1][0] == pad.height - 1
        assert pad.addstr_calls[-1][2] == "hello"

    def test_append_writes_segments_at_increasing_columns(self):
        pad = FakePad(height=5, width=40)
        ring = RingLog(maxlen=100, pad=pad)
        ring.append([("ab", None, None, False), ("cd", None, None, False)], "abcd")
        cols = [call[1] for call in pad.addstr_calls[-2:]]
        assert cols == [0, 2]

    def test_append_truncates_at_pad_width(self):
        pad = FakePad(height=5, width=4)
        ring = RingLog(maxlen=100, pad=pad)
        ring.append([("this is way too long", None, None, False)], "this is way too long")
        text = pad.addstr_calls[-1][2]
        assert len(text) <= 4

    def test_append_never_writes_to_last_column(self):
        # Regression: writing all the way to a pad's last column makes ncurses
        # auto-wrap the cursor, which — with scrollok(True) and the cursor already on
        # the pad's last row — triggers an extra implicit scroll (a spurious blank row
        # after every line that exactly fills the terminal width).
        pad = FakePad(height=5, width=10)
        ring = RingLog(maxlen=100, pad=pad)
        ring.append([("0123456789", None, None, False)], "0123456789")  # exactly pad width
        col, text = pad.addstr_calls[-1][1], pad.addstr_calls[-1][2]
        assert col + len(text) <= pad.width - 1

    def test_append_uses_pair_cache_for_colored_segments(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        pad = FakePad()
        ring = RingLog(maxlen=100, pad=pad, pair_cache=cache)
        ring.append([("red", 1, None, False)], "red")
        attr = pad.addstr_calls[-1][3]
        assert attr == cache.attr_for(1, None, False)

    def test_append_plain_segment_has_zero_attr(self):
        fc = FakeCurses()
        cache = PairCache(fc)
        pad = FakePad()
        ring = RingLog(maxlen=100, pad=pad, pair_cache=cache)
        ring.append([("plain", None, None, False)], "plain")
        assert pad.addstr_calls[-1][3] == 0

    def test_pad_and_plain_text_stay_1to1_aligned_over_many_lines(self):
        pad = FakePad(height=5, width=40)
        ring = RingLog(maxlen=3, pad=pad)
        for i in range(10):
            ring.append([(f"line{i}", None, None, False)], f"line{i}")
        assert len(ring) == 3 == len(ring.plain_lines())
        assert ring.plain_lines() == ['line7', 'line8', 'line9']

    # ── reattach()/detach() — surviving a mid-run disable/re-enable cycle ────────

    def test_detach_stops_drawing_but_keeps_history(self):
        pad = FakePad()
        ring = RingLog(maxlen=100, pad=pad)
        ring.append([("a", None, None, False)], "a")
        ring.detach()
        calls_before = len(pad.addstr_calls)
        ring.append([("b", None, None, False)], "b")  # pad detached -- must not touch it
        assert len(pad.addstr_calls) == calls_before
        assert ring.plain_lines() == ["a", "b"]

    def test_reattach_replays_full_history_onto_new_pad(self):
        ring = RingLog(maxlen=100)  # no pad yet
        ring.append([("a", None, None, False)], "a")
        ring.append([("b", None, None, False)], "b")
        new_pad = FakePad(height=5, width=40)
        ring.reattach(new_pad, None)
        # both prior lines got replayed (scrolled+written) onto the fresh pad
        assert new_pad.scroll_calls == 2
        texts = [call[2] for call in new_pad.addstr_calls]
        assert texts == ["a", "b"]

    def test_reattach_with_none_pad_is_a_no_op(self):
        ring = RingLog(maxlen=100)
        ring.append([("a", None, None, False)], "a")
        ring.reattach(None, None)  # must not raise
        assert ring.plain_lines() == ["a"]

    def test_detach_then_reattach_preserves_history_across_two_pads(self):
        pad1 = FakePad(height=5, width=40)
        ring = RingLog(maxlen=100, pad=pad1)
        ring.append([("first", None, None, False)], "first")
        ring.detach()
        ring.append([("during-gap", None, None, False)], "during-gap")  # recorded, not drawn
        pad2 = FakePad(height=5, width=40)
        ring.reattach(pad2, None)
        assert ring.plain_lines() == ["first", "during-gap"]
        assert [c[2] for c in pad2.addstr_calls] == ["first", "during-gap"]
        assert pad1.addstr_calls == [(pad1.height - 1, 0, "first", 0)]  # pad1 never saw the gap line


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
