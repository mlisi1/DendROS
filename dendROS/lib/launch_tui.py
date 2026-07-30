"""Full-screen TUI render path for `ros2 launch` (launch_mode: tui).

Architecture
------------
Pure layer (importable and unit-testable without a real curses/tty):
  - quantize_rgb_to_256 / segments_from_ansi : ANSI SGR -> (text, fg256, bg256, bold) runs.
  - wrap_line   : hard-wraps one line's colored segments into rows of at most N columns,
                  splitting mid-segment so color survives a wrap boundary.
  - PairCache   : lazily allocates/reuses curses color-pair slots, LRU-evicted when exhausted.
  - RingLog     : bounded scrollback (collections.deque of (segments, plain_text)) — the sole
                  source of truth for history. Nothing is projected onto a persistent curses
                  pad; rendering is computed on demand for whatever window is actually visible
                  (visible_rows()), wrapped at the current terminal width (set_width()). A
                  resize is therefore just "wrap differently on the next redraw", and a mid-run
                  disable/re-enable cycle needs no explicit replay step — a freshly reopened
                  session just reads RingLog again. A future `/` search is a scan of the
                  plain-text index translated back into a wrapped row; no data-model change
                  needed.

Curses-owning layer (manual-testing only — same accepted gap as dendros_config.py's own curses
interaction, which is likewise untested by the unit suite):
  - run_tui : spawns ONE long-lived background reader thread (persists for the whole run, not
    per-session) that consumes the same _iter_stdin() generator the classic loop uses. While a TUI
    session is open it does the existing per-line work (crash-alert detection, colorize,
    param-watcher drain) and pushes tagged data onto that session's queue.Queue() — it never
    touches curses objects directly. run_tui() then loops calling curses.wrapper(_tui_main, ...):
    each call is one TUI "session" (fresh PairCache/queue), and _tui_main returns 'disabled'
    when `dendros disable` fires mid-run from another terminal, at which point run_tui() waits
    (polling the same shared flag) for either a re-enable — reopening a fresh session that reads
    the *entire* persisted RingLog, including lines recorded during the passthrough gap, so nothing
    is fragmented — or the launch process ending while still disabled, in which case it just
    returns (waiting around for a re-enable after the process already exited would look like a
    hang, not a feature).
  - _tui_main : one curses.wrapper session. Drains its queue on a 50ms tick, appends to RingLog,
    redraws a pinned single-row header (the colored [dendROS] tag + dim "vX.Y.Z" version string,
    on a fixed dark background so the bar visually stands out from the scrolling content —
    curses/terminfo can't introspect the terminal's actual background color, so this is a fixed
    shade rather than a computed offset from it; crash/param alerts via ca.set_sink() shifted right
    of the tag+version so nothing overlaps) and the scrollback body — each redraw asks RingLog to
    rewrap at the current width and hand back exactly the wrapped rows needed for the viewport,
    drawn straight onto the main window (no pad) — and handles keyboard navigation
    (PageUp/PageDown/Home/End, now paging by wrapped rows rather than logical lines) and
    KEY_RESIZE (clears stale content; the next tick's redraw picks up the new size and rewraps).
    'q' only quits once the launch process has exited (eof) — quitting early would leave it
    running with no visible output and no way back in; Ctrl-C is still the way to actually stop
    it, same as classic mode. A redraw is skipped on ticks where nothing changed (no new queued
    content, no key that moved the view) to avoid needless rewrapping work at the 20Hz tick rate.

Ctrl-C handling is intentionally different from the classic loop: SIGINT is only ever delivered to
the main thread, so the background reader thread's blocking read() never sees it and _iter_stdin()'s
own first-interrupt handling never fires there. The main thread's getch() loop catches
KeyboardInterrupt itself and calls ca_module.enter_shutdown_mode() directly instead.
"""

import collections
import locale
import queue
import re
import sys
import threading
import time

from lib import __version__
from lib.colors import DENDROS_TAG
from lib.config_loader import resolve_node
from lib.global_config import is_disable_flag_set

# Fixed color for the header row's background — curses/terminfo has no way to read back
# the terminal's actual default background color, so this can't be "computed" as an offset
# from it. Most dark-theme terminals use a dark *grey* rather than literal black (e.g.
# ~(30,30,30)), so a subtly-darker charcoal barely registered against them — true black
# gives reliable, visible contrast against essentially any theme, light or dark, which is
# why it's the standard choice for status/title bars in terminal UIs generally.
_HEADER_BG_RGB = (0, 0, 0)

# Matches any CSI sequence (not just SGR color codes ending in 'm') so non-color codes
# like '\033[K' (erase-to-end-of-line, used by param_watcher's inverted style — curses
# already handles its own line clearing via clrtoeol()) get silently stripped instead of
# showing up as literal garbage text in the pad.
_CSI_RE = re.compile(r'\033\[([0-9;]*)([A-Za-z])')


# xterm's 6x6x6 color cube (indices 16-231) does NOT use evenly-spaced steps — the actual
# per-channel levels are 0, 95, 135, 175, 215, 255 (a big jump from 0, smaller steps after).
# Naively rounding to 6 *linear* steps of 255/5 picks badly wrong levels for darker colors
# specifically (e.g. a dark grey (24,24,26) rounded that way lands on cube level 1 = 95,
# a much brighter navy-tinted color, not a neutral dark grey).
_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)


def _nearest_cube_level(v):
    """Return (level_index, level_value) closest to v among _CUBE_LEVELS."""
    best_i, best_v, best_d = 0, _CUBE_LEVELS[0], abs(v - _CUBE_LEVELS[0])
    for i, lv in enumerate(_CUBE_LEVELS):
        d = abs(v - lv)
        if d < best_d:
            best_i, best_v, best_d = i, lv, d
    return best_i, best_v


def quantize_rgb_to_256(r, g, b):
    """Map a 24-bit RGB triple to the nearest xterm-256 color index (16-231 color cube,
    or 232-255 grayscale ramp — whichever is actually closer).

    curses can't portably render real truecolor without hijacking the terminal's global
    palette, so TUI mode accepts a 256-color approximation; classic mode stays exact since
    it writes raw ANSI straight through.
    """
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))

    ri, rv = _nearest_cube_level(r)
    gi, gv = _nearest_cube_level(g)
    bi, bv = _nearest_cube_level(b)
    cube_idx = 16 + 36 * ri + 6 * gi + bi
    cube_dist = (r - rv) ** 2 + (g - gv) ** 2 + (b - bv) ** 2

    # Grayscale ramp: 24 steps from 8 to 238 in increments of 10 (indices 232-255).
    gray = round((r + g + b) / 3)
    gray_idx = max(0, min(23, round((gray - 8) / 10)))
    gray_val = 8 + gray_idx * 10
    gray_dist = (r - gray_val) ** 2 + (g - gray_val) ** 2 + (b - gray_val) ** 2

    if gray_dist < cube_dist:
        return 232 + gray_idx
    return cube_idx


def _parse_sgr_params(code_str):
    """Yield (n, kind, value) for each SGR parameter in a raw code string.

    kind is 'rgb' (value=(r,g,b)) for 38;2/48;2, '256' (value=idx) for 38;5/48;5,
    or 'code' (value=None) for a plain numeric SGR code.
    """
    parts = code_str.split(';') if code_str else ['0']
    i = 0
    while i < len(parts):
        p = parts[i]
        n = int(p) if p.isdigit() else 0
        if n in (38, 48) and i + 1 < len(parts):
            mode = parts[i + 1]
            if mode == '2' and i + 4 < len(parts):
                try:
                    r, g, b = int(parts[i + 2]), int(parts[i + 3]), int(parts[i + 4])
                except ValueError:
                    yield (n, 'code', None)
                    i += 1
                    continue
                yield (n, 'rgb', (r, g, b))
                i += 5
                continue
            elif mode == '5' and i + 2 < len(parts):
                try:
                    idx = int(parts[i + 2])
                except ValueError:
                    yield (n, 'code', None)
                    i += 1
                    continue
                yield (n, '256', idx)
                i += 3
                continue
        yield (n, 'code', None)
        i += 1


def segments_from_ansi(line, quantize=quantize_rgb_to_256):
    """Parse an already-colorized line into (text, fg256_or_None, bg256_or_None, bold) runs."""
    segments = []
    fg = None
    bg = None
    bold = False
    pos = 0
    for m in _CSI_RE.finditer(line):
        text = line[pos:m.start()]
        if text:
            segments.append((text, fg, bg, bold))
        pos = m.end()
        if m.group(2) != 'm':
            continue  # non-SGR CSI code (e.g. '\033[K') — already stripped, nothing to apply
        for n, kind, val in _parse_sgr_params(m.group(1)):
            if n == 0:
                fg = bg = None
                bold = False
            elif n == 1:
                bold = True
            elif n == 22:
                bold = False
            elif n == 7:
                # Reverse video (used by tag_style: inverted — ansi_code + ';7').
                # DendROS's own inverted convention is colored background + black hollow
                # text (see param_watcher's _fg_to_bg, which builds the same look via
                # explicit codes) — use explicit black here rather than curses' "default"
                # foreground (-1), which renders as the terminal's default text color
                # (usually white/light-grey) instead of hollow black.
                bg = fg if fg is not None else bg
                fg = 0
            elif n == 38:
                if kind == 'rgb':
                    fg = quantize(*val)
                elif kind == '256':
                    fg = val
            elif n == 48:
                if kind == 'rgb':
                    bg = quantize(*val)
                elif kind == '256':
                    bg = val
            elif 30 <= n <= 37:
                fg = n - 30
            elif 90 <= n <= 97:
                fg = (n - 90) + 8
            elif 40 <= n <= 47:
                bg = n - 40
            elif 100 <= n <= 107:
                bg = (n - 100) + 8
            elif n == 39:
                fg = None
            elif n == 49:
                bg = None
    tail = line[pos:]
    if tail:
        segments.append((tail, fg, bg, bold))
    return segments


def wrap_line(segments, width):
    """Hard-wrap one line's colored segments into rows of at most `width` columns.

    Splits mid-segment where needed so color survives a wrap boundary. Character-wrap
    (not word-wrap) — matches how classic passthrough / less / vim already wrap raw
    terminal output, and log content (stack traces, JSON, URLs) has no reliable "word"
    unit to break on anyway. Always returns at least one row: an empty line yields a
    single empty row, so blank log lines still occupy a row like a real terminal.
    """
    width = max(1, width)
    rows = []
    current = []
    col = 0
    for text, fg, bg, bold in segments:
        while text:
            remaining = width - col
            if remaining <= 0:
                rows.append(current)
                current = []
                col = 0
                remaining = width
            chunk, text = text[:remaining], text[remaining:]
            if chunk:
                current.append((chunk, fg, bg, bold))
                col += len(chunk)
    rows.append(current)
    return rows


class PairCache:
    """Lazily allocates/reuses curses color-pair slots, LRU-evicted when COLOR_PAIRS is exhausted.

    `curses_module` is injectable so tests can pass a fake with just the handful of
    attributes actually used (init_pair, color_pair, COLOR_PAIRS, A_BOLD).
    """

    def __init__(self, curses_module, max_pairs=None):
        self._curses = curses_module
        self._pairs = collections.OrderedDict()  # (fg, bg) -> pair_number, LRU order
        self._max_pairs = max_pairs
        self._free_numbers = None

    def _capacity(self):
        if self._max_pairs is not None:
            return max(1, self._max_pairs)
        return max(1, getattr(self._curses, 'COLOR_PAIRS', 64) - 1)

    def get_pair(self, fg=-1, bg=-1):
        """Return a curses pair number for (fg, bg), allocating or reusing one as needed."""
        key = (fg, bg)
        if key in self._pairs:
            self._pairs.move_to_end(key)
            return self._pairs[key]

        if self._free_numbers is None:
            self._free_numbers = list(range(self._capacity(), 0, -1))

        if self._free_numbers:
            pair_num = self._free_numbers.pop()
        else:
            _, pair_num = self._pairs.popitem(last=False)  # evict least-recently-used

        self._curses.init_pair(pair_num, fg, bg)
        self._pairs[key] = pair_num
        return pair_num

    def attr_for(self, fg=None, bg=None, bold=False):
        """Return the combined curses attribute (color pair + bold) for one rendered segment."""
        pair_num = self.get_pair(-1 if fg is None else fg, -1 if bg is None else bg)
        attr = self._curses.color_pair(pair_num)
        if bold:
            attr |= getattr(self._curses, 'A_BOLD', 0)
        return attr


class RingLog:
    """Bounded scrollback: (segments, plain_text) pairs, 1:1 aligned by construction.

    `_lines` is the sole source of truth — nothing is projected onto a persistent curses
    pad. Rendering is computed on demand for whatever window is actually visible (see
    visible_rows()), wrapped at the current terminal width (see set_width()). This means
    a resize is just "wrap differently next redraw", and a mid-run system-wide
    disable/re-enable cycle needs no explicit replay step: a freshly reopened TUI session
    just reads `_lines` again on its next redraw, including whatever passthrough-gap lines
    the reader thread appended directly while curses was torn down.

    append() is called both from the main thread (draining the session queue) and directly
    by the background reader thread during a disable gap, so every mutating method takes a
    lock.
    """

    def __init__(self, maxlen):
        self.maxlen = maxlen
        self._lines = collections.deque(maxlen=maxlen)
        self._row_counts = collections.deque(maxlen=maxlen)
        self._wrap_width = None
        self._total_rows = 0
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._lines)

    def __getitem__(self, idx):
        return self._lines[idx]

    def plain_lines(self):
        return [plain for _, plain in self._lines]

    def append(self, segments, plain_text):
        with self._lock:
            evicted_rows = 0
            if self.maxlen is not None and len(self._lines) == self.maxlen:
                evicted_rows = self._row_counts[0]
            self._lines.append((segments, plain_text))
            row_count = len(wrap_line(segments, self._wrap_width)) if self._wrap_width else 1
            self._row_counts.append(row_count)
            self._total_rows += row_count - evicted_rows

    def set_width(self, width):
        """Rewrap the entire retained history at a new width. No-op if unchanged — this
        is the only O(history) operation, and it only runs once per actual resize, never
        once per redraw tick."""
        width = max(1, width)
        with self._lock:
            if width == self._wrap_width:
                return
            self._wrap_width = width
            self._row_counts = collections.deque(
                (len(wrap_line(segments, width)) for segments, _ in self._lines),
                maxlen=self.maxlen,
            )
            self._total_rows = sum(self._row_counts)

    def total_rows(self):
        return self._total_rows

    def visible_rows(self, view_offset, height):
        """Return up to `height` wrapped rows, ending `view_offset` rows back from the
        tail. Only wraps as many lines as needed to cover the request — cost scales with
        how far back the view is scrolled plus the viewport height, not total history."""
        with self._lock:
            width = self._wrap_width or 1
            height = max(0, height)
            view_offset = max(0, view_offset)
            need = view_offset + height
            collected_rev = []  # rows in reverse (newest-first) order while accumulating
            for segments, _ in reversed(self._lines):
                if len(collected_rev) >= need:
                    break
                collected_rev.extend(reversed(wrap_line(segments, width)))
            collected_rev.reverse()
            end = max(0, len(collected_rev) - view_offset)
            start = max(0, end - height)
            return collected_rev[start:end]


# ── Curses-owning layer (manual-testing only) ──────────────────────────────────

def run_tui(stdin_lines, colorize_fn, ca_module, pw_module, param_alert, param_alert_style,
            color_map, tag_map, style_map, tag_style, show_tag, global_cfg):
    """Entry point called from dendROS_pipe.py::main() when launch_mode is 'tui'.

    The reader thread is spawned once here and lives for the whole run — it, and the
    RingLog scrollback it feeds, both persist across a mid-run `dendros disable` /
    `dendros enable` cycle: disabling tears down curses and switches the reader to direct
    passthrough printing (recording those plain-text lines into the same RingLog rather
    than discarding them), and re-enabling reopens curses, which reads the *entire*
    history — including the passthrough gap — straight from RingLog on its next redraw.
    No fragmented logs, and no explicit replay step needed (RingLog isn't pad-backed).

    Returns once the whole run is genuinely over: either a normal quit ('q', only
    available once the launch process has exited) or the process ending while disabled.
    """
    import curses
    locale.setlocale(locale.LC_ALL, '')  # required for curses to render multi-byte UTF-8

    try:
        scrollback = int(global_cfg.get('tui_scrollback_lines', 5000))
    except (TypeError, ValueError):
        scrollback = 5000
    scrollback = max(1, scrollback)

    ring = RingLog(maxlen=scrollback)  # width set per-redraw via set_width(); survives resizes
    passthrough_event = threading.Event()  # set = no curses right now, reader prints raw
    stop_event = threading.Event()  # set once = stdin_lines is exhausted, for good
    session = {'q': None}  # current session's queue.Queue(), or None while disabled

    def _reader():
        try:
            for line in stdin_lines:
                if passthrough_event.is_set():
                    # Disabled: curses is torn down (or tearing down). Relay directly,
                    # same as classic mode's passthrough, but also keep it in the
                    # scrollback (as a plain/uncolored entry) so a later re-enable can
                    # replay the *complete* history — nothing gets lost in the gap.
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    plain = line.rstrip('\r\n')
                    ring.append([(plain, None, None, False)], plain)
                    continue
                if ca_module._crash_alert_enabled:
                    dead_node, exit_code = ca_module.detect_death(line)
                    if dead_node:
                        code, _ = resolve_node(dead_node, color_map, tag_map)
                        ca_module.record_death(dead_node, exit_code, code)
                        ca_module.print_alert_banner()
                    else:
                        restarted = ca_module.detect_restart(line)
                        if restarted:
                            ca_module.handle_restart(restarted)
                colored = colorize_fn(line)
                q = session['q']
                if q is not None:
                    q.put(('line', colored))
                    if param_alert:
                        for notif in pw_module.drain(color_map, tag_map, style_map, tag_style,
                                                      show_tag, param_alert_style):
                            q.put(('line', notif))
        except Exception:
            pass
        finally:
            q = session['q']
            if q is not None:
                q.put(('eof', None))
            stop_event.set()

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    while True:
        result = curses.wrapper(_tui_main, ring, session, passthrough_event, stop_event, ca_module)
        if result != 'disabled':
            return  # normal quit — fully done

        # Disabled mid-run: wait for either a re-enable (reopen the TUI) or the launch
        # process ending entirely while we were disabled (nothing left to reopen for —
        # sitting around indefinitely after the process already exited would look like
        # a hang, not a feature).
        while not stop_event.is_set() and is_disable_flag_set():
            time.sleep(0.5)
        if stop_event.is_set():
            return
        # else: flag cleared while still running — loop back and reopen curses


def _tui_main(scr, ring, session, passthrough_event, stop_event, ca_module):
    import curses

    curses.curs_set(0)
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    scr.timeout(50)
    scr.keypad(True)

    pair_cache = PairCache(curses)
    _header_bg = quantize_rgb_to_256(*_HEADER_BG_RGB)

    max_y, max_x = scr.getmaxyx()
    # Header: a single row — the colored [dendROS] tag + a dim version string — on a fixed
    # dark background so it stands out from the scrolling content below. Crash/param alerts
    # render to the right of the tag+version (see _draw_banner) so they never overlap it.
    banner_h = 1
    _header_segments = segments_from_ansi(DENDROS_TAG)
    _version_text = f' v{__version__} '

    q = queue.Queue()
    session['q'] = q
    # A valid queue must be in place *before* the reader is told it's safe to use it —
    # only then do we clear this (it was left set from a prior disable, or is already
    # clear on the very first open).
    passthrough_event.clear()
    banner_state = {'text': ''}

    ca_module.set_sink(lambda text: q.put(('banner', text)))
    if ca_module._dead_nodes:
        # Reopening with a node already dead from before — surface that immediately
        # instead of waiting for the next death/restart event to refresh the banner.
        ca_module.print_alert_banner()

    view_offset = 0  # 0 = following the live tail; >0 = scrolled back N rows
    eof = stop_event.is_set()
    interrupted = False
    _last_disable_check = 0.0

    def _disabled_system_wide():
        # Rate-limited to ~1/sec, matching the classic loop's _refresh_disabled_state().
        nonlocal _last_disable_check
        now = time.monotonic()
        if now - _last_disable_check < 1.0:
            return False
        _last_disable_check = now
        return is_disable_flag_set()

    def _drain_queue():
        nonlocal eof
        drained = False
        while True:
            try:
                kind, payload = q.get_nowait()
            except queue.Empty:
                break
            drained = True
            if kind == 'line':
                # Lines still carry their trailing \r/\n from _iter_stdin(); curses'
                # addstr() treats an embedded newline as a real cursor action (an extra
                # implicit line-advance), producing a spurious blank row between every
                # entry if left in.
                segments = segments_from_ansi(payload.rstrip('\r\n'))
                plain = ''.join(seg[0] for seg in segments)
                ring.append(segments, plain)
            elif kind == 'banner':
                banner_state['text'] = payload
            elif kind == 'eof':
                eof = True
        return drained

    def _draw_segments(row, col, usable_width, segments, default_bg=None):
        # default_bg fills in for segments with no explicit background of their own (e.g.
        # plain [dendROS]-tag/version text) — used for the header row so its dark
        # background shows through instead of reverting to the terminal's own default.
        # Segments that DO carry their own bg (e.g. a red crash-alert banner) keep it.
        for seg_text, fg, bg, bold in segments:
            if col >= usable_width:
                break
            eff_bg = bg if bg is not None else default_bg
            attr = pair_cache.attr_for(fg, eff_bg, bold) if (fg is not None or eff_bg is not None or bold) else 0
            try:
                scr.addstr(row, col, seg_text[:max(0, usable_width - col)], attr)
            except curses.error:
                pass
            col += len(seg_text)
        return col

    def _draw_banner(width):
        usable_width = max(0, width - 1)  # never write to the last column — see _redraw()
        row = 0

        header_attr = pair_cache.attr_for(None, _header_bg, False)
        try:
            scr.bkgdset(' ', header_attr)
        except curses.error:
            pass
        scr.move(row, 0)
        scr.clrtoeol()

        col = _draw_segments(row, 0, usable_width, _header_segments, default_bg=_header_bg)
        try:
            scr.addstr(row, col, _version_text[:max(0, usable_width - col)], header_attr | curses.A_DIM)
        except curses.error:
            pass
        col += len(_version_text)
        alert_col = min(usable_width, col + 1)  # small gap, then alerts to the right of the tag+version

        text = banner_state['text']
        if not text:
            if eof:
                hint = '-- process finished -- q: quit  PageUp/PageDown: scroll --'
                try:
                    scr.addstr(row, alert_col, hint[:max(0, usable_width - alert_col)], header_attr | curses.A_DIM)
                except curses.error:
                    pass
        else:
            _draw_segments(row, alert_col, usable_width, segments_from_ansi(text), default_bg=_header_bg)

    def _redraw():
        nonlocal view_offset
        max_y, max_x = scr.getmaxyx()
        log_h = max(1, max_y - banner_h)
        usable_width = max(1, max_x - 1)  # never write to the last column — see below

        ring.set_width(usable_width)  # no-op unless the terminal was actually resized
        max_offset = max(0, ring.total_rows() - log_h)
        view_offset = min(view_offset, max_offset)

        _draw_banner(max_x)
        # _draw_banner() left scr's window-wide background set to the header's dark
        # fill (bkgdset() applies to the whole window, not just row 0 — harmless when
        # the body lived on a separate pad, but body rows are drawn directly on `scr`
        # now, so leaving it set would paint every blank body cell black instead of
        # the terminal's actual default background). Reset before touching the body.
        try:
            scr.bkgdset(' ', 0)
        except curses.error:
            pass

        rows = ring.visible_rows(view_offset, log_h)
        row_i = 0
        for wrapped_row in rows:
            scr_row = banner_h + row_i
            try:
                scr.move(scr_row, 0)
                scr.clrtoeol()
            except curses.error:
                pass
            _draw_segments(scr_row, 0, usable_width, wrapped_row)
            row_i += 1
        # Blank out any rows below the last one drawn (e.g. early in a run, before
        # there's enough history to fill the screen, or after the window grew).
        while row_i < log_h:
            scr_row = banner_h + row_i
            try:
                scr.move(scr_row, 0)
                scr.clrtoeol()
            except curses.error:
                pass
            row_i += 1

        scr.noutrefresh()
        curses.doupdate()

    needs_redraw = True  # always draw once before the first getch()
    try:
        while True:
            if _disabled_system_wide():
                # `dendros disable` from another terminal — tear the TUI down cleanly
                # (curses.wrapper's own finally still restores the terminal), switch the
                # reader to passthrough printing, and let run_tui() decide whether to
                # wait for a re-enable or give up (see run_tui's own loop). No pad to
                # detach from — a freshly reopened session just reads `ring` again.
                passthrough_event.set()
                session['q'] = None
                return 'disabled'

            drained = _drain_queue()
            if needs_redraw or drained:
                _redraw()
                needs_redraw = False

            try:
                ch = scr.getch()
            except KeyboardInterrupt:
                if interrupted:
                    break
                interrupted = True
                ca_module.enter_shutdown_mode()
                continue

            if ch == -1:
                # Timeout, no key pressed. Even once the launch process exits (eof), stay open
                # so the user can keep scrolling/reading — same as scrollback in a normal
                # terminal doesn't vanish just because the foreground process ended.
                continue

            needs_redraw = True

            if ch == curses.KEY_RESIZE:
                # Wipe stale content from a shrink; the next _redraw() recomputes
                # everything fresh from scr.getmaxyx() (same "just re-read the size and
                # redraw fully every tick" approach dendros_config.py already relies on
                # — no resize_term()/update_lines_cols() dance needed on this platform).
                scr.clear()
            elif ch in (curses.KEY_PPAGE, curses.KEY_NPAGE, curses.KEY_HOME, curses.KEY_END):
                log_h = max(1, scr.getmaxyx()[0] - banner_h)
                max_offset = max(0, ring.total_rows() - log_h)
                if ch == curses.KEY_PPAGE:
                    view_offset = min(max_offset, view_offset + log_h)
                elif ch == curses.KEY_NPAGE:
                    view_offset = max(0, view_offset - log_h)
                elif ch == curses.KEY_HOME:
                    view_offset = max_offset
                elif ch == curses.KEY_END:
                    view_offset = 0
            elif ch == ord('q') and eof:
                # Only quit once the launch process has actually exited — quitting the
                # TUI while it's still running would leave it alive with no visible
                # output and no way back in. Ctrl-C is the way to actually stop it,
                # same as it always is.
                break
    finally:
        try:
            ca_module.set_sink(None)
        except Exception:
            pass
    return None
