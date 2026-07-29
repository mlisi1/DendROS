"""Full-screen TUI render path for `ros2 launch` (launch_mode: tui).

Architecture
------------
Pure layer (importable and unit-testable without a real curses/tty):
  - quantize_rgb_to_256 / segments_from_ansi : ANSI SGR -> (text, fg256, bg256, bold) runs.
  - PairCache   : lazily allocates/reuses curses color-pair slots, LRU-evicted when exhausted.
  - RingLog     : bounded scrollback (collections.deque) that also projects each appended line
                  onto a curses pad (or a fake pad double, for tests) via a single append() call,
                  keeping pad content and a parallel plain-text index 1:1 aligned (ready for a
                  future `/` search without a data-model change). Its pad/pair_cache are
                  session-scoped (reattach()/detach()) but the deque itself survives a mid-run
                  disable/re-enable cycle — see below.

Curses-owning layer (manual-testing only — same accepted gap as dendros_config.py's own curses
interaction, which is likewise untested by the unit suite):
  - run_tui : spawns ONE long-lived background reader thread (persists for the whole run, not
    per-session) that consumes the same _iter_stdin() generator the classic loop uses. While a TUI
    session is open it does the existing per-line work (crash-alert detection, colorize,
    param-watcher drain) and pushes tagged data onto that session's queue.Queue() — it never
    touches curses objects directly. run_tui() then loops calling curses.wrapper(_tui_main, ...):
    each call is one TUI "session" (fresh pad/PairCache/queue), and _tui_main returns 'disabled'
    when `dendros disable` fires mid-run from another terminal, at which point run_tui() waits
    (polling the same shared flag) for either a re-enable — reopening a fresh session that replays
    the *entire* persisted RingLog, including lines recorded during the passthrough gap, so nothing
    is fragmented — or the launch process ending while still disabled, in which case it just
    returns (waiting around for a re-enable after the process already exited would look like a
    hang, not a feature).
  - _tui_main : one curses.wrapper session. Drains its queue on a 50ms tick, appends to RingLog,
    redraws a pinned single-row header (the colored [dendROS] tag + dim "vX.Y.Z" version string,
    on a fixed dark background so the bar visually stands out from the scrolling content —
    curses/terminfo can't introspect the terminal's actual background color, so this is a fixed
    shade rather than a computed offset from it; crash/param alerts via ca.set_sink() shifted right
    of the tag+version so nothing overlaps) and the scrollback pad, and handles keyboard navigation
    (PageUp/PageDown/Home/End). 'q' only quits once the launch process has exited (eof) — quitting
    early would leave it running with no visible output and no way back in; Ctrl-C is still the way
    to actually stop it, same as classic mode.

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

    Each append() both stores the line and (if a pad is attached) projects it onto the pad —
    scroll(1) then addstr the new line at the pad's fixed last row — so the pad and the
    plain-text index can never drift apart. A future `/` search is a scan of the plain-text
    side translated back into a pad row; no data-model change needed.

    Survives a mid-run system-wide disable/re-enable cycle: the TUI can tear down curses
    (detach()) and later reopen a fresh session (reattach()) without losing scrollback —
    only the pad/pair_cache are session-scoped, the deque itself is not. append() is also
    called directly by the background reader thread while curses is torn down (recording
    plain-text passthrough lines for later replay), so every mutating method takes a lock —
    detach()/reattach() run on the main thread exactly at the moment the reader thread's
    policy (queue vs. call append() directly) flips, and this guards against the two ever
    touching `_pad`/`_lines` concurrently.
    """

    def __init__(self, maxlen, pad=None, pair_cache=None):
        self.maxlen = maxlen
        self._lines = collections.deque(maxlen=maxlen)
        self._pad = pad
        self._pair_cache = pair_cache
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._lines)

    def __getitem__(self, idx):
        return self._lines[idx]

    def plain_lines(self):
        return [plain for _, plain in self._lines]

    def append(self, segments, plain_text):
        with self._lock:
            self._lines.append((segments, plain_text))
            if self._pad is not None:
                self._render_last(segments)

    def reattach(self, pad, pair_cache):
        """Attach a fresh pad/pair_cache and replay all stored history onto it — used when
        the TUI reopens after a disable/re-enable cycle; the scrollback was never lost,
        only the curses session was torn down."""
        with self._lock:
            self._pad = pad
            self._pair_cache = pair_cache
            if pad is None:
                return
            for segments, _ in self._lines:
                self._render_last(segments)

    def detach(self):
        """Detach from the (about-to-be-destroyed) pad, e.g. right before curses tears down.
        Safe to keep calling append() afterward — it'll just store lines without drawing
        until reattach() is called again."""
        with self._lock:
            self._pad = None
            self._pair_cache = None

    def _render_last(self, segments):
        pad = self._pad
        try:
            max_y, max_x = pad.getmaxyx()
        except Exception:
            return
        # Never write all the way to the last column: ncurses auto-wraps the cursor to
        # the next row once a write reaches a window/pad's final cell, which (with
        # scrollok(True) and the cursor already on the pad's last row) triggers an
        # *extra* implicit scroll — producing a spurious blank row after every line
        # that happens to exactly fill the terminal width.
        usable_x = max(0, max_x - 1)
        pad.scroll(1)
        row = max(0, max_y - 1)
        try:
            pad.move(row, 0)
            pad.clrtoeol()
        except Exception:
            pass
        col = 0
        for text, fg, bg, bold in segments:
            if col >= usable_x:
                break
            attr = 0
            if self._pair_cache is not None and (fg is not None or bg is not None or bold):
                attr = self._pair_cache.attr_for(fg, bg, bold)
            try:
                pad.addstr(row, col, text[:max(0, usable_x - col)], attr)
            except Exception:
                pass
            col += len(text)


# ── Curses-owning layer (manual-testing only) ──────────────────────────────────

def run_tui(stdin_lines, colorize_fn, ca_module, pw_module, param_alert, param_alert_style,
            color_map, tag_map, style_map, tag_style, show_tag, global_cfg):
    """Entry point called from dendROS_pipe.py::main() when launch_mode is 'tui'.

    The reader thread is spawned once here and lives for the whole run — it, and the
    RingLog scrollback it feeds, both persist across a mid-run `dendros disable` /
    `dendros enable` cycle: disabling tears down curses and switches the reader to direct
    passthrough printing (recording those plain-text lines into the same RingLog rather
    than discarding them), and re-enabling reopens curses with the *entire* history —
    including the passthrough gap — replayed into a fresh pad. No fragmented logs.

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

    ring = RingLog(maxlen=scrollback)  # pad attached per-session via reattach()/detach()
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

    pad = curses.newpad(ring.maxlen, max(1, max_x))
    pad.scrollok(True)
    pad.idlok(True)
    ring.reattach(pad, pair_cache)  # first-ever open: no-op replay. Reopen: full history.

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
                # implicit line-advance on top of our own pad.scroll(1)), producing a
                # spurious blank row between every entry if left in.
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
        usable_width = max(0, width - 1)  # never write to the last column — see RingLog._render_last
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
        max_y, max_x = scr.getmaxyx()
        log_h = max(1, max_y - banner_h)
        _draw_banner(max_x)
        scr.noutrefresh()
        pad_h, pad_w = pad.getmaxyx()
        top = max(0, pad_h - log_h - view_offset)
        try:
            pad.noutrefresh(top, 0, banner_h, 0, max_y - 1, max_x - 1)
        except curses.error:
            pass
        curses.doupdate()

    try:
        while True:
            if _disabled_system_wide():
                # `dendros disable` from another terminal — tear the TUI down cleanly
                # (curses.wrapper's own finally still restores the terminal). Detach the
                # ring *before* the reader is allowed to touch it directly (the ordering
                # here, plus RingLog's own lock, is what keeps this race-free), then
                # switch the reader to passthrough printing and let run_tui() decide
                # whether to wait for a re-enable or give up (see run_tui's own loop).
                passthrough_event.set()
                session['q'] = None
                ring.detach()
                return 'disabled'

            _drain_queue()
            _redraw()

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

            pad_h, _ = pad.getmaxyx()
            _, max_x = scr.getmaxyx()
            log_h = max(1, scr.getmaxyx()[0] - banner_h)
            max_offset = max(0, pad_h - log_h)
            if ch in (curses.KEY_PPAGE,):
                view_offset = min(max_offset, view_offset + log_h)
            elif ch in (curses.KEY_NPAGE,):
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
