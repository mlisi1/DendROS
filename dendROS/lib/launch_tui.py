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
                  session just reads RingLog again. visible_rows() also doubles as a generic
                  "N rows ending M back from the tail" query usable for an arbitrary historical
                  range (e.g. a copy-mode yank), not just the live viewport, and tags each row
                  with is_continuation (True = a mid-line wrap, not the start of a new logical
                  line) so callers can reconstruct text without inserting spurious newlines at
                  wrap points. A future `/` search is a scan of the plain-text index translated
                  back into a wrapped row; no data-model change needed.
  - selection_span_for_row / extract_selection_text / build_osc52_sequence : text-selection
                  math and clipboard encoding — see the "Mouse selection" paragraph below.
  - decode_sgr_mouse / decode_navigation_key / screen_row_to_tail_offset : raw escape-
                  sequence decoding and the screen-to-content coordinate mapping selection
                  needs — see below.
  - find_clipboard_tool / copy_via_system_clipboard_tool : local xclip/xsel/wl-copy
                  fallback for terminals that don't honor OSC 52 — see below.
  - compute_scrollbar_thumb : the vertical scrollbar's thumb position/size — see below.

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
    content, no key that moved the view) to avoid needless rewrapping work at the 20Hz tick rate
    — and, just as importantly, to guarantee a scrolled-back (or actively-selected) view's cells
    are never rewritten by content arriving elsewhere (some terminals clear an active selection
    on *any* output from the child process, not just visible changes, so simply relying on
    curses' physical/virtual screen diffing to make a same-content redraw a no-op wasn't enough).

Mouse selection (always on, no mode key): click-drag selects text with DendROS rendering its own
highlight (sel_anchor/sel_cursor, an (offset, col) pair each, in the same tail-relative units as
view_offset) rather than relying on the terminal's native selection — a real drag auto-copies to the
system clipboard on release, X11-primary-selection style, no keychord required. Two other approaches
were tried and rejected first: (1) leaving selection entirely native, which is a hard architectural
dead end no matter how carefully it's implemented — native selection is tied to on-screen *cell*
contents, so it's destroyed by any repaint, deliberate scroll included; (2) a keyboard-driven copy
mode ('v' to enter, hjkl/arrows to move, Space to anchor, 'y' to yank) which *did* structurally
survive scrolling (see below) but required an explicit mode switch the user didn't want — the goal is
behavior indistinguishable from a native terminal except that the selection survives scrolling and
new output, which native selection never does.

An earlier, separate attempt at DendROS-owned *mouse* selection (via curses.mousemask()/getmouse())
was also tried and abandoned before the keyboard detour, on the mistaken assumption that raw drag
reporting is inherently unreliable across terminals. The likelier cause: getmouse() decodes the legacy
X10 mouse protocol, which packs coordinates into single bytes with a fixed offset — it corrupts past
column ~223 and has real event-queue bugs, matching the reported symptoms ("random lines" on a plain
click, selection dying "after a while"). This implementation instead enables the modern SGR (1006)
extended protocol directly via raw escape sequences (see _tui_main's setup) and parses the reports
itself (decode_sgr_mouse(), _read_escape_sequence()), bypassing curses.mousemask()/getmouse() entirely
— SGR has no coordinate ceiling and has been supported by every mainstream terminal, including VTE
(Terminator, GNOME Terminal), for many years. A terminal that only speaks the legacy protocol (no SGR
'<' marker) deliberately produces no mouse event at all rather than decoding the byte-packed form —
"modern terminal required" for mouse selection, same accepted-limitation stance as OSC 52 below;
keyboard scrolling is unaffected regardless.

Getting raw SGR bytes to actually reach _read_escape_sequence() intact needed one more, unrelated fix,
found only by testing against a real pty (writing raw bytes to a pty master and logging exactly what
scr.getch() returned on the other end, rather than guessing): with the curses default of
scr.keypad(True), ncurses recognizes the "ESC[<" prefix as matching its own built-in mouse handling
and emits a premature, unbuffered KEY_MOUSE (409) the instant it sees '<' — *without* ever calling
curses.mousemask() — and the rest of the report's bytes then leak through as bogus literal keystrokes
on later getch() calls, which is why the first cut of this design (plain click/drag doing nothing,
wheel scroll dead, only Shift-click native selection working) looked like total failure rather than a
protocol bug. _tui_main calls scr.keypad(False) instead — curses then does no terminfo-based key
translation at all, so arrows, Home/End/PageUp/PageDown, and mouse reports all arrive as raw,
unmolested bytes (verified the same pty way) and are hand-decoded here (decode_navigation_key() for
the former). curses.KEY_RESIZE is unaffected by keypad() either way — it's synthesized from SIGWINCH,
independent of terminfo key matching (also pty-verified).

Selection survives scrolling and new output for the same structural reason the keyboard version did:
sel_anchor/sel_cursor are content-relative positions, not screen positions, so _redraw() recomputes
the correct highlight for whatever's currently visible on every redraw — the highlighted *text* is
what's tracked. _sync_pin() (used by both _redraw() and the mouse-event handler, so a click is always
mapped against up-to-date coordinates) applies the same tail-growth delta compensation to
sel_anchor/sel_cursor that a scrolled-back view_offset already gets, and "pinned" (excluded from the
redraw-skip logic's "follows the tail" case) now means sel_anchor is not None, generalizing what used
to be copy_mode's job. Extraction (extract_selection_text()) and clipboard encoding
(build_osc52_sequence(), written directly with os.write() — bypassing curses' screen buffer since it's
a non-printing control sequence) are unchanged from the keyboard version. OSC 52 support isn't
universal (solid in iTerm2/kitty/foot/Windows Terminal/xterm-with-allowWindowOps; confirmed *absent*
in some VTE-based terminals — Terminator included, verified directly: a raw OSC 52 write from the
shell, outside this app entirely, reached no clipboard) — a real, documented limitation, not a bug,
since there's no portable way to detect support from inside the app. tmux/screen need their own mouse
passthrough enabled (`set -g mouse on`) and, for OSC 52 specifically, clipboard passthrough
(`set -g set-clipboard on` / `allow-passthrough`) to actually reach the host clipboard — same class of
externally-configured limitation. Because of that, a release also tries `copy_via_system_clipboard_tool()`
(`xclip`/`xsel`/`wl-copy`, whichever is found on PATH first, via `shutil.which()` + `subprocess.run()`) —
this reaches the real X11/Wayland clipboard directly on a local session regardless of terminal OSC 52
support, at the cost of an optional external dependency; if none of the three are installed it's a
silent no-op and OSC 52 remains the only (best-effort) path, which still matters for an over-SSH or
tmux-passthrough session a local clipboard tool can't reach at all. Neither path confirms the clipboard
was actually reached (OSC 52 has no acknowledgement, and a local tool not raising isn't proof either —
e.g. no DISPLAY), so a successful *attempt* through both is what triggers the "Copied" header toast
(`copy_toast_state['at']`, drawn right-aligned in `_draw_banner()`): full brightness, then normal, then
dim, over `_COPY_TOAST_DIM_UNTIL` seconds, the closest curses gets to a fade without true alpha
blending. Once `find_clipboard_tool()` finds nothing at session start, `_draw_banner()` instead shows a
persistent low-priority hint (`-- copy needs xclip/xsel/wl-copy (none found) --`) whenever the header
would otherwise be idle, so the limitation is surfaced before a drag rather than discovered after one.
The toast needs its own timer-driven redraw, independent of the usual needs_redraw/header_changed/
drained gates (see the main loop's `copy_toast_active`/`toast_changed`) — safe to redraw for regardless
of a scrolled-back or actively-selected view, since it repaints the exact same underlying content every
time, just with a different header corner; nothing about it touches `sel_anchor`/`sel_cursor`/`view_offset`.

The real terminal scrollbar is inert on the alternate screen buffer curses uses, so `_redraw()` draws
its own in a dedicated column: one more column is reserved beyond the pre-existing "never write to the
last column" buffer (a known curses trouble spot, the bottom-right cell in particular, that the rest of
this file already sidesteps uniformly rather than special-casing) — `usable_width` shrinks by one
extra column for this, in both `_redraw()` and `_screen_to_content()` (kept in sync so click mapping
doesn't drift off from what's actually drawn). `compute_scrollbar_thumb()` (pure, unit-tested) turns
`view_offset`/`max_offset`/`total_rows` into a track-relative thumb position and size — the thumb sits
at the *bottom* when following the tail and the *top* when fully scrolled back (a log viewer's
convention, position 0 = newest), track-only (no thumb) when there's nothing to scroll. Drawing it is
split out into its own `_draw_scrollbar()` (self-contained: recomputes its own geometry, calls
`_sync_pin()` itself) specifically so it can run *without* a full body `_redraw()` — the main loop's
`elif drained:` branch calls it alone whenever the full redraw was skipped (a pinned/scrolled-back
view) but new output still landed in the ring, keeping the thumb's position current even while the
body itself stays frozen for that pin. This was a real, reported bug in the first cut: with a
selection held, the scrollbar visually froze wherever it was when the pin started, since it was only
ever drawn as part of the same full `_redraw()` the body's protection was skipping — it looked like
"still at the tail" even as output kept arriving underneath, only catching up once the user next
scrolled or clicked (which happened to trigger `_sync_pin()` directly). The scrollbar has no content of
its own to protect the way the body does, so there's no reason it needs to share the body's skip.

Enabling mouse tracking (1002+1006) turns off the terminal's own wheel-to-arrow-key auto-translation
that classic-mode scrolling used to ride for free, so wheel events are decoded explicitly from SGR
wheel button codes (64/65) instead — see the ch == 27 branch in the main loop. ESCDELAY (curses' own
ambiguous-escape resolution delay) is irrelevant here and left at its default: it only applies to
keypad(True)'s terminfo matching, which is off; _read_escape_sequence's own short scr.timeout(5) poll
is what decides a lone Escape has no sequence following it, independent of ESCDELAY entirely.

Ctrl-C handling is intentionally different from the classic loop: SIGINT is only ever delivered to
the main thread, so the background reader thread's blocking read() never sees it and _iter_stdin()'s
own first-interrupt handling never fires there. The main thread's getch() loop catches
KeyboardInterrupt itself and calls ca_module.enter_shutdown_mode() directly instead.
"""

import base64
import collections
import locale
import os
import queue
import re
import shutil
import subprocess
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


# ── Copy-mode selection logic (pure — no curses) ────────────────────────────────
#
# Positions are (offset, col) pairs, where `offset` is a row's distance-from-tail in the
# same units as RingLog.visible_rows()'s view_offset (0 = the newest row, larger = older),
# and `col` is a character column within that row's plain text. This is the same
# addressing already used for scrolling, so a selection anchor/cursor pins against tail
# growth exactly the way a scrolled-back view already does — see _redraw() in _tui_main.

def _selection_bounds(anchor, cursor):
    """Order an (anchor, cursor) pair into (lo_offset, lo_col, hi_offset, hi_col), where
    `hi` is the older/reading-order-first endpoint (larger offset) and `lo` is the
    newer/reading-order-last endpoint (smaller offset)."""
    a_offset, a_col = anchor
    c_offset, c_col = cursor
    if a_offset > c_offset or (a_offset == c_offset and a_col > c_col):
        return c_offset, c_col, a_offset, a_col
    return a_offset, a_col, c_offset, c_col


def selection_span_for_row(row_tail_offset, row_len, anchor, cursor):
    """Return the inclusive (start_col, end_col) column range of `row_tail_offset` that's
    covered by the anchor-to-cursor selection, or None if that row isn't part of it (or
    there's no active selection, i.e. `anchor` is None)."""
    if anchor is None:
        return None
    lo_offset, lo_col, hi_offset, hi_col = _selection_bounds(anchor, cursor)
    if not (lo_offset <= row_tail_offset <= hi_offset):
        return None
    if hi_offset == lo_offset:
        return (min(hi_col, lo_col), max(hi_col, lo_col))
    if row_tail_offset == hi_offset:
        return (hi_col, max(0, row_len - 1))
    if row_tail_offset == lo_offset:
        return (0, lo_col)
    return (0, max(0, row_len - 1))


def extract_selection_text(rows, anchor, cursor):
    """Join `rows` (as returned by RingLog.visible_rows() for exactly the anchor-to-cursor
    span, oldest first) into the text a copy-mode yank should produce: continuation rows
    (mid-line wraps) are concatenated with no separator since they're one flowed logical
    line, rows that start a new logical line get a real newline before them, and the
    first/last row are trimmed to the selection's column bounds (both inclusive)."""
    if anchor is None or not rows:
        return ''
    lo_offset, lo_col, hi_offset, hi_col = _selection_bounds(anchor, cursor)
    n = len(rows)
    pieces = []
    for i, (segments, is_continuation) in enumerate(rows):
        text = ''.join(seg[0] for seg in segments)
        if n == 1:
            text = text[min(hi_col, lo_col):max(hi_col, lo_col) + 1]
        elif i == 0:
            text = text[hi_col:]
        elif i == n - 1:
            text = text[:lo_col + 1]
        if i > 0 and not is_continuation:
            pieces.append('\n')
        pieces.append(text)
    return ''.join(pieces)


def screen_row_to_tail_offset(body_row, n_rows, view_offset):
    """Given a 0-based row index within the drawn log body, how many rows were actually
    drawn (n_rows, from RingLog.visible_rows()), and the current view_offset, return that
    row's tail-relative offset (same convention as visible_rows()/selection_span_for_row()),
    or None if body_row is outside what was actually drawn."""
    if body_row < 0 or body_row >= n_rows:
        return None
    return (n_rows - 1 - body_row) + view_offset


def compute_scrollbar_thumb(track_height, view_offset, max_offset, total_rows):
    """Return (thumb_start, thumb_height), both in track-row units (0 = top of track), for
    a vertical scrollbar representing view_offset's position within total_rows of
    scrollback, viewed through a track_height-row window. view_offset follows RingLog's own
    convention (0 = at the tail/newest, max_offset = fully scrolled back/oldest), so the
    thumb sits at the *bottom* of the track when following the tail and at the *top* when
    fully scrolled back -- matching how a log/scrollback viewer's scrollbar conventionally
    reads (as opposed to a document viewer's, where position 0 is the top). Returns
    (0, 0) -- no thumb, just an empty track -- when there's nothing to scroll."""
    track_height = max(0, track_height)
    if track_height == 0 or max_offset <= 0 or total_rows <= track_height:
        return 0, 0
    thumb_height = max(1, min(track_height, round(track_height * track_height / total_rows)))
    max_thumb_start = track_height - thumb_height
    frac = max(0.0, min(1.0, view_offset / max_offset))  # 0 = at tail, 1 = fully scrolled back
    thumb_start = max(0, min(max_thumb_start, round(max_thumb_start * (1 - frac))))
    return thumb_start, thumb_height


def decode_sgr_mouse(cb, cx, cy, terminator):
    """Decode an SGR mouse report's (Cb, Cx, Cy, terminator) into a plain dict. Cb's low 2
    bits are button/direction, bit 5 (32) is the motion flag, bit 6 (64) is the wheel flag
    (in which case the low bits distinguish up(0)/down(1) instead of a button). Modifier
    bits (4/8/16 = Shift/Meta/Ctrl) are ignored — they don't overlap those bits and aren't
    acted on here. Cx/Cy are 1-based (raw wire format); converted to 0-based to match
    curses' own row/col convention."""
    is_release = terminator == 'm'
    is_motion = bool(cb & 32)
    is_wheel = bool(cb & 64)
    button = cb & 0x03
    return {
        'button': button,
        'is_motion': is_motion,
        'is_wheel': is_wheel,
        'is_release': is_release,
        'wheel_dir': ('up' if button == 0 else 'down') if is_wheel else None,
        'col': cx - 1,
        'row': cy - 1,
    }


# Two CSI encodings exist for the same navigation keys across terminals: a bare final
# letter (ESC[A -> up) and a numbered tilde form (ESC[5~ -> page_up) -- xterm/VTE use both
# depending on the key, so both are supported. Left/right are decoded for completeness
# (matching real key semantics) even though nothing in _tui_main currently binds them.
_NAV_LETTER_ACTIONS = {'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left', 'H': 'home', 'F': 'end'}
_NAV_TILDE_ACTIONS = {'1': 'home', '7': 'home', '4': 'end', '8': 'end', '5': 'page_up', '6': 'page_down'}


def decode_navigation_key(final_byte, digits=''):
    """Decode a CSI navigation sequence into an action string ('up'/'down'/'left'/'right'/
    'home'/'end'/'page_up'/'page_down'), or None if unrecognized. `final_byte` is '~' for
    the digit-prefixed tilde form (with `digits` the accumulated digit string, e.g. '5' for
    PageUp), or the bare terminating letter (A/B/C/D/H/F) for the other form, with no
    digits."""
    if final_byte == '~':
        return _NAV_TILDE_ACTIONS.get(digits)
    if digits:
        return None
    return _NAV_LETTER_ACTIONS.get(final_byte)


_OSC52_MAX_BYTES = 1024 * 1024  # soft guard against a pathologically large selection


def build_osc52_sequence(text, max_bytes=_OSC52_MAX_BYTES):
    """Build the OSC 52 "set system clipboard" escape sequence for `text`. Support isn't
    universal across terminals (solid in iTerm2/kitty/foot/Windows Terminal/xterm-with-
    allowWindowOps; confirmed absent in some VTE-based terminals, Terminator included) —
    there's no portable way to detect support from inside the app, so this is a real,
    documented limitation rather than something DendROS can paper over; see
    copy_via_system_clipboard_tool() for the fallback this limitation motivated. UTF-8
    payload is silently truncated past `max_bytes` — not expected to matter for realistic
    log-line selections.
    """
    data = text.encode('utf-8', errors='replace')[:max_bytes]
    b64 = base64.b64encode(data).decode('ascii')
    return f'\033]52;c;{b64}\a'.encode('ascii')


# Tried in order; the first one found on PATH is used. All three write to the system
# clipboard directly (bypassing terminal OSC 52 support entirely) on a local X11/Wayland
# session -- xclip/xsel need an X server, wl-copy needs a Wayland compositor, so exactly
# one pair is normally relevant on any given machine and the other(s) simply won't be
# installed/found, not an error.
_CLIPBOARD_COMMANDS = (
    ('xclip', '-selection', 'clipboard'),
    ('xsel', '--clipboard', '--input'),
    ('wl-copy',),
)


def find_clipboard_tool(which_fn=shutil.which):
    """Return the first clipboard command from _CLIPBOARD_COMMANDS found on PATH, or None
    if none are installed. `which_fn` is injectable for testing without touching the real
    PATH."""
    for cmd in _CLIPBOARD_COMMANDS:
        if which_fn(cmd[0]):
            return cmd
    return None


def copy_via_system_clipboard_tool(text, which_fn=shutil.which, run_fn=subprocess.run):
    """Best-effort copy to the real system clipboard via a local CLI tool, as a fallback
    for terminals (VTE-based ones confirmed, Terminator included) that don't honor OSC 52
    at all — see build_osc52_sequence()'s docstring. Returns True if a tool was found and
    ran without raising (not a guarantee the clipboard was actually reached — e.g. no
    DISPLAY/Wayland session, or the process erroring internally, still count as "ran"), or
    False if no known tool was found on PATH. `which_fn`/`run_fn` are injectable for
    testing. Errors (missing DISPLAY, tool crash, etc.) are swallowed rather than raised —
    this is always a supplementary write alongside the OSC 52 escape sequence, never the
    only attempt, so failing silently here just means falling back to that."""
    cmd = find_clipboard_tool(which_fn)
    if cmd is None:
        return False
    try:
        run_fn(cmd, input=text.encode('utf-8', errors='replace'), timeout=2, check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return True


# "Copied" header toast timing: shown bold, then normal, then dim, then gone -- curses has
# no true alpha blending, so this is the closest approximation of a fade using discrete
# attribute steps. Durations are cumulative thresholds against elapsed time since the copy.
_COPY_TOAST_TEXT = 'Copied'
_COPY_TOAST_BOLD_UNTIL = 1.2  # how long it stays fully visible before fading starts
_COPY_TOAST_NORMAL_UNTIL = 1.3  # fade stage 1 -- quick, not the lingering part
_COPY_TOAST_DIM_UNTIL = 1.4  # fade stage 2, also the total display duration


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
        """Return up to `height` (segments, is_continuation) rows, ending `view_offset`
        rows back from the tail. `is_continuation` is True for a row that's a mid-line
        wrap continuation (no real line break belongs before it) and False for a row that
        starts a new logical line — lets callers (e.g. a copy-mode yank) reconstruct text
        without inserting spurious newlines at wrap points. Only wraps as many lines as
        needed to cover the request — cost scales with how far back the view is scrolled
        plus the viewport height, not total history. Also usable for an arbitrary
        historical range, not just the live viewport: e.g. `view_offset=min(a, b),
        height=abs(a - b) + 1` returns exactly the rows between two tail-relative offsets
        `a` and `b`."""
        with self._lock:
            width = self._wrap_width or 1
            height = max(0, height)
            view_offset = max(0, view_offset)
            need = view_offset + height
            collected_rev = []  # (segments, is_continuation), newest-first while accumulating
            for segments, _ in reversed(self._lines):
                if len(collected_rev) >= need:
                    break
                wrapped = wrap_line(segments, width)
                tagged = [(row, i > 0) for i, row in enumerate(wrapped)]
                collected_rev.extend(reversed(tagged))
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


_MAX_SGR_PROBE_BYTES = 32  # generous for "Cb;Cx;Cy" decimal digits; bounds a malformed burst


def _tui_main(scr, ring, session, passthrough_event, stop_event, ca_module):
    import curses

    curses.curs_set(0)
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    scr.timeout(50)
    # keypad(False), deliberately -- NOT the usual curses default. With keypad(True),
    # ncurses recognizes the "ESC[<" SGR mouse prefix as a match against its own built-in
    # mouse handling and emits a premature KEY_MOUSE (409) the instant it sees '<', without
    # buffering the rest of the report -- confirmed via a pty experiment (raw bytes written
    # to a pty master, curses.getch() output logged on the other end): the trailing bytes
    # ("0;10;5M" etc.) then leak through as bogus literal keystrokes on subsequent getch()
    # calls. This happens even though curses.mousemask() is never called. With keypad(False),
    # curses does no terminfo-based key translation at all, so every byte after ESC arrives
    # raw and intact, one getch() call at a time (also confirmed the same way) -- arrow keys,
    # PageUp/PageDown/Home/End, and mouse reports are hand-decoded from those raw bytes below
    # instead (_read_escape_sequence()). curses.KEY_RESIZE is unaffected either way -- it's
    # synthesized from SIGWINCH, entirely independent of keypad()'s terminfo matching.
    scr.keypad(False)

    def _read_escape_sequence():
        # Called right after getch() returns 27 (ESC). Distinguishes a bare Escape keypress
        # from a CSI sequence (ESC [ ...) and, for the latter, decodes either an SGR mouse
        # report (ESC [ < Cb ; Cx ; Cy M-or-m) or a navigation key (ESC [ <letter>, or
        # ESC [ <digits> ~) -- see the module docstring's "Mouse selection" paragraph and
        # the keypad(False) comment above for why hand-parsing every byte here, rather than
        # letting curses translate it, is what actually works. Returns ('mouse', event_dict),
        # ('nav', action_string), or None (bare Escape / unrecognized — a byte read while
        # probing for the '[' prefix is pushed back via curses.ungetch() when it doesn't
        # match, so a genuine standalone Escape isn't lost; bytes consumed mid-sequence are
        # deliberately NOT pushed back, since reinterpreting a torn fragment as literal
        # keystrokes would be worse than silently dropping one event).
        scr.timeout(5)  # bytes should already be buffered (one pty write) -- brief poll
        try:
            c1 = scr.getch()
            if c1 != ord('['):
                if c1 != -1:
                    curses.ungetch(c1)
                return None
            c2 = scr.getch()
            if c2 == ord('<'):
                digits = []
                terminator = None
                for _ in range(_MAX_SGR_PROBE_BYTES):
                    c = scr.getch()
                    if c == -1:
                        break
                    if c in (ord('M'), ord('m')):
                        terminator = chr(c)
                        break
                    digits.append(chr(c))
                if terminator is None:
                    return None  # incomplete/malformed -- drop silently, see above
                try:
                    cb_str, cx_str, cy_str = ''.join(digits).split(';')
                    cb, cx, cy = int(cb_str), int(cx_str), int(cy_str)
                except ValueError:
                    return None
                return ('mouse', decode_sgr_mouse(cb, cx, cy, terminator))
            if c2 in (ord('A'), ord('B'), ord('C'), ord('D'), ord('H'), ord('F')):
                action = decode_navigation_key(chr(c2))
                return ('nav', action) if action else None
            digits = []
            c = c2
            for _ in range(4):  # generous; real tilde sequences are 1-2 digits
                if c == -1:
                    return None
                if ord('0') <= c <= ord('9'):
                    digits.append(chr(c))
                    c = scr.getch()
                    continue
                if c == ord('~'):
                    action = decode_navigation_key('~', ''.join(digits))
                    return ('nav', action) if action else None
                return None
            return None
        finally:
            scr.timeout(50)

    # Mouse tracking is enabled directly via raw escape sequences rather than
    # curses.mousemask()/getmouse(), which decode the legacy X10 protocol (single-byte
    # coordinates, corrupts past column ~223) — see the module docstring's "Mouse
    # selection" paragraph. 1002 = press/release + motion-while-a-button-is-held; 1006 =
    # SGR extended coordinate encoding. The whole session below is bracketed in the outer
    # try/finally so the disable sequence always fires on every exit path (normal quit,
    # mid-run `dendros disable` returning 'disabled', or an exception) -- curses.wrapper()'s
    # own teardown doesn't know about a mode it never enabled, so this is this function's
    # responsibility every session, not a one-time thing in run_tui(). flushinp() discards
    # stray buffered bytes from before this session started reading -- matters both on
    # first open and on every re-open after a disable gap, during which nothing reads
    # stdin (a stray click there would otherwise leave garbage bytes for the next session).
    try:
        os.write(1, b'\x1b[?1002h\x1b[?1006h')
        curses.flushinp()
    except OSError:
        pass
    try:
        return _run_tui_session(scr, ring, session, passthrough_event, stop_event,
                                 ca_module, curses, _read_escape_sequence)
    finally:
        try:
            os.write(1, b'\x1b[?1006l\x1b[?1002l')
        except OSError:
            pass


def _run_tui_session(scr, ring, session, passthrough_event, stop_event, ca_module,
                      curses, _read_escape_sequence):
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
    copy_toast_state = {'at': None}  # monotonic() timestamp of the last copy, or None

    ca_module.set_sink(lambda text: q.put(('banner', text)))
    if ca_module._dead_nodes:
        # Reopening with a node already dead from before — surface that immediately
        # instead of waiting for the next death/restart event to refresh the banner.
        ca_module.print_alert_banner()

    view_offset = 0  # 0 = following the live tail; >0 = scrolled back N rows, pinned to
                      # that same absolute content as new rows arrive (see _redraw())
    last_total_rows = 0  # ring.total_rows() as of the last redraw/scroll-key, for the pin
    eof = stop_event.is_set()
    interrupted = False
    _last_disable_check = 0.0

    # Mouse-driven text selection: sel_anchor (press point) / sel_cursor (current drag or
    # last release point), both None or (offset, col) in the same tail-relative units as
    # view_offset — see the module docstring's "Mouse selection" paragraph. Always on, no
    # mode toggle. Invariant: sel_anchor is None <=> sel_cursor is None.
    sel_anchor = None
    sel_cursor = None
    mouse_down = False  # True between a left-button press and its matching release
    # Checked once per session, not per-frame — a PATH lookup is cheap but pointless to
    # repeat 20 times a second for a value that can't change mid-session.
    _clipboard_tool_missing = find_clipboard_tool() is None

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

    def _draw_segments(row, col, usable_width, segments, default_bg=None, sel_span=None):
        # default_bg fills in for segments with no explicit background of their own (e.g.
        # plain [dendROS]-tag/version text) — used for the header row so its dark
        # background shows through instead of reverting to the terminal's own default.
        # Segments that DO carry their own bg (e.g. a red crash-alert banner) keep it.
        if sel_span is None:
            # Fast path: batch-write each same-attr run in one addstr() call. Used for
            # every row except the handful touched by an active selection, which need
            # character-granular attribute overlay (see below).
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

        # Selection path: one addstr() per character so the highlight (curses.A_REVERSE,
        # matching how a native terminal renders its own selection) can be OR'd onto the
        # character's normal attribute rather than replacing its color outright.
        for seg_text, fg, bg, bold in segments:
            eff_bg = bg if bg is not None else default_bg
            base_attr = pair_cache.attr_for(fg, eff_bg, bold) if (fg is not None or eff_bg is not None or bold) else 0
            for ch in seg_text:
                if col >= usable_width:
                    return col
                attr = base_attr
                if sel_span[0] <= col <= sel_span[1]:
                    attr |= curses.A_REVERSE
                try:
                    scr.addstr(row, col, ch, attr)
                except curses.error:
                    pass
                col += 1
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
            elif _clipboard_tool_missing:
                # Lowest-priority hint — only shown while idle (no crash/param alert, not
                # eof yet). OSC 52 alone can't be relied on (see the module docstring), so
                # without a local clipboard tool on PATH, a mouse-drag selection's copy
                # step is silently a no-op — worth surfacing rather than leaving the user
                # to discover it only after dragging something they wanted to keep.
                hint = '-- copy needs xclip/xsel/wl-copy (none found) --'
                try:
                    scr.addstr(row, alert_col, hint[:max(0, usable_width - alert_col)], header_attr | curses.A_DIM)
                except curses.error:
                    pass
        else:
            _draw_segments(row, alert_col, usable_width, segments_from_ansi(text), default_bg=_header_bg)

        copied_at = copy_toast_state['at']
        if copied_at is not None:
            elapsed = time.monotonic() - copied_at
            if elapsed < _COPY_TOAST_BOLD_UNTIL:
                toast_attr = header_attr | curses.A_BOLD
            elif elapsed < _COPY_TOAST_NORMAL_UNTIL:
                toast_attr = header_attr
            elif elapsed < _COPY_TOAST_DIM_UNTIL:
                toast_attr = header_attr | curses.A_DIM
            else:
                toast_attr = None  # fully faded -- main loop clears copy_toast_state, not us
            if toast_attr is not None:
                # Right-aligned in the header's own corner, independent of (and drawn after,
                # so it wins any overlap with) the left-aligned alert/hint area.
                msg_col = max(alert_col, usable_width - len(_COPY_TOAST_TEXT))
                try:
                    scr.addstr(row, msg_col, _COPY_TOAST_TEXT[:max(0, usable_width - msg_col)], toast_attr)
                except curses.error:
                    pass

    def _sync_pin(log_h):
        # Shared pin/delta-compensation: "pinned" (don't let tail growth silently drift
        # what's shown) now covers both a scrolled-back view_offset and an active/just-
        # finished selection (sel_anchor is not None) — a strict generalization of what
        # used to be gated on copy_mode alone. Left alone, new lines arriving would mean
        # the *absolute* rows shown (or the selected content) silently drift forward even
        # though the user never touched anything — exactly what breaks a terminal-native
        # selection over scrolled-back content, just relocated to app-owned state instead.
        # Called both from _redraw() and directly before mapping a mouse click's screen
        # coordinates (see _screen_to_content) — idempotent when called twice with no
        # intervening ring changes (delta is 0 the second time), so that's safe.
        nonlocal view_offset, sel_anchor, sel_cursor, last_total_rows
        current_total = ring.total_rows()
        delta = current_total - last_total_rows
        if delta and (sel_anchor is not None or view_offset > 0):
            view_offset += delta
            if sel_anchor is not None:
                sel_anchor = (sel_anchor[0] + delta, sel_anchor[1])
            if sel_cursor is not None:
                sel_cursor = (sel_cursor[0] + delta, sel_cursor[1])
        last_total_rows = current_total
        max_offset = max(0, current_total - log_h)
        view_offset = max(0, min(view_offset, max_offset))
        return max_offset

    def _screen_to_content(mouse_row, mouse_col):
        # Maps a clicked/dragged screen (row, col) to a content-relative (offset, col),
        # mirroring _redraw()'s own row loop below so it can't drift out of sync with what
        # was actually drawn. Caller must have just called _sync_pin() so view_offset is
        # current — otherwise a click could be mapped against stale (pre-tail-growth)
        # content, the same class of bug the pin logic exists to prevent elsewhere.
        max_y, max_x = scr.getmaxyx()
        log_h = max(1, max_y - banner_h)
        usable_width = max(1, max_x - 2)  # scrollbar column + one reserved buffer — see _redraw()
        body_row = mouse_row - banner_h
        if body_row < 0:
            return None  # click landed on the header row
        rows = ring.visible_rows(view_offset, log_h)
        n_rows = len(rows)
        if n_rows == 0:
            return None
        if body_row >= n_rows:
            body_row = n_rows - 1  # clicked in blank padding below content
        row_tail_offset = screen_row_to_tail_offset(body_row, n_rows, view_offset)
        segments, _is_continuation = rows[body_row]
        row_len = sum(len(seg[0]) for seg in segments)
        col = max(0, min(mouse_col, usable_width - 1))
        col = min(col, max(0, row_len - 1) if row_len else 0)
        return (row_tail_offset, col)

    def _draw_scrollbar():
        # Self-contained (recomputes its own geometry and calls _sync_pin() itself) so it
        # can be called on its own, without a full body _redraw(), on ticks where the body
        # redraw is being skipped to protect a pinned/selected view — the scrollbar has no
        # content of its own to protect, so it shouldn't go stale just because the body
        # does. _sync_pin() is idempotent (delta is 0 if something else already called it
        # this tick), so a redundant call here is harmless. See the module docstring's
        # "Mouse selection" paragraph and the main loop's `elif drained:` branch.
        max_y, max_x = scr.getmaxyx()
        log_h = max(1, max_y - banner_h)
        usable_width = max(1, max_x - 2)  # keep in sync with _redraw()/_screen_to_content()
        scrollbar_col = usable_width
        max_offset = _sync_pin(log_h)
        thumb_start, thumb_height = compute_scrollbar_thumb(log_h, view_offset, max_offset,
                                                             ring.total_rows())
        for row_i in range(log_h):
            scr_row = banner_h + row_i
            try:
                if thumb_start <= row_i < thumb_start + thumb_height:
                    scr.addstr(scr_row, scrollbar_col, ' ', curses.A_REVERSE)
                else:
                    scr.addstr(scr_row, scrollbar_col, '│', curses.A_DIM)
            except curses.error:
                pass

    def _redraw():
        max_y, max_x = scr.getmaxyx()
        log_h = max(1, max_y - banner_h)
        # Column budget: content (0..usable_width-1), then the scrollbar column
        # (usable_width), then one more reserved-but-never-written column (usable_width+1
        # == max_x-1) kept exactly as before — writing to a window's true last column is a
        # known curses trouble spot (the bottom-right cell in particular), and the rest of
        # this file already avoided it uniformly rather than special-casing just that one
        # cell; the scrollbar gets its own column instead of reclaiming that buffer.
        usable_width = max(1, max_x - 2)

        ring.set_width(usable_width)  # no-op unless the terminal was actually resized
        _sync_pin(log_h)

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
        n_rows = len(rows)
        row_i = 0
        for wrapped_row, _is_continuation in rows:
            scr_row = banner_h + row_i
            # Row at screen position row_i (top=0) is this many rows back from the tail —
            # see RingLog.visible_rows()'s own offset convention. selection_span_for_row()
            # already returns None for every row when sel_anchor is None, so no extra gate
            # is needed here.
            row_tail_offset = screen_row_to_tail_offset(row_i, n_rows, view_offset)
            row_len = sum(len(seg[0]) for seg in wrapped_row)
            sel_span = selection_span_for_row(row_tail_offset, row_len, sel_anchor, sel_cursor)
            try:
                scr.move(scr_row, 0)
                scr.clrtoeol()
            except curses.error:
                pass
            _draw_segments(scr_row, 0, usable_width, wrapped_row, sel_span=sel_span)
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

        # Vertical scrollbar in the reserved right column — the real terminal scrollbar is
        # inert on the alternate screen buffer, so this is the only position feedback
        # available in TUI mode.
        _draw_scrollbar()

        scr.noutrefresh()
        curses.doupdate()

    needs_redraw = True  # always draw once before the first getch()
    prev_banner_text = banner_state['text']
    prev_eof = eof
    prev_copy_toast_active = False
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
            # Draining always happens (cheap bookkeeping into RingLog), but an actual
            # redraw — any curses write at all — only happens when something the user can
            # currently see changed. While scrolled back (view_offset > 0), new tail lines
            # land outside the pinned viewport and must NOT trigger a redraw: relying on
            # curses' own physical/virtual diffing to make "redraw with identical content"
            # a no-op turned out not to be enough — most terminal emulators clear an active
            # selection reactively on *any* output from the child process, whether or not
            # the bytes actually change visible content. Not calling doupdate() at all is
            # the only way to guarantee zero terminal writes, and therefore a guaranteed-
            # untouched selection, for a pinned scroll-back view.
            header_changed = banner_state['text'] != prev_banner_text or eof != prev_eof
            # The "Copied" toast fades over a fixed wall-clock duration, independent of any
            # key/output activity — needs its own timer-driven redraw while active (every
            # tick, to animate the fade stages) plus one more once it crosses from active to
            # expired (to actually erase it; copy_toast_active alone would go straight from
            # True to absent with no redraw in between otherwise). This is safe to redraw
            # for regardless of the scrolled-back/active-selection pin: it repaints the same
            # underlying content every time, just with a different header corner — nothing
            # about it can disturb sel_anchor/sel_cursor or move view_offset.
            copy_toast_active = False
            if copy_toast_state['at'] is not None:
                if time.monotonic() - copy_toast_state['at'] < _COPY_TOAST_DIM_UNTIL:
                    copy_toast_active = True
                else:
                    copy_toast_state['at'] = None  # expired; this tick's redraw erases it
            toast_changed = copy_toast_active != prev_copy_toast_active
            # An active selection (sel_anchor is not None) always counts as "not following
            # the tail", even at view_offset 0: guarantees new output can't repaint the
            # screen out from under a selection the user is making or has just made.
            viewport_follows_tail = (sel_anchor is None) and (view_offset == 0)
            if (needs_redraw or header_changed or copy_toast_active or toast_changed
                    or (drained and viewport_follows_tail)):
                _redraw()
                prev_banner_text = banner_state['text']
                prev_eof = eof
                prev_copy_toast_active = copy_toast_active
                needs_redraw = False
            elif drained:
                # The full body redraw was skipped (view pinned by an active selection or
                # a scrolled-back view_offset), but new output DID just land in the ring —
                # the scrollbar has no content to protect the way the body does, so keep it
                # live independently rather than leaving it showing wherever it was when the
                # pin started (this was the actual reported bug: with a selection held, the
                # scrollbar visually froze in place even as more output kept arriving below
                # it, only catching up once the user next scrolled or clicked).
                _draw_scrollbar()
                scr.noutrefresh()
                curses.doupdate()

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
            elif ch == 27:
                # keypad(False) means curses does no key translation at all — every arrow
                # key, PageUp/PageDown/Home/End, and mouse report arrives as a raw ESC-
                # prefixed byte sequence here; see _read_escape_sequence and the module
                # docstring's "Mouse selection" paragraph. None = bare Escape, nothing
                # bound to it.
                result = _read_escape_sequence()
                if result is None:
                    pass
                elif result[0] == 'nav':
                    action = result[1]
                    if action in ('page_up', 'page_down', 'home', 'end', 'up', 'down'):
                        log_h = max(1, scr.getmaxyx()[0] - banner_h)
                        max_offset = _sync_pin(log_h)  # also lets an active selection
                                                        # survive keyboard scrolling
                        if action == 'page_up':
                            view_offset = min(max_offset, view_offset + log_h)
                        elif action == 'page_down':
                            view_offset = max(0, view_offset - log_h)
                        elif action == 'home':
                            view_offset = max_offset
                        elif action == 'end':
                            view_offset = 0
                        elif action == 'up':
                            view_offset = min(max_offset, view_offset + 1)
                        elif action == 'down':
                            view_offset = max(0, view_offset - 1)
                    # 'left'/'right' intentionally unbound.
                else:  # result[0] == 'mouse'
                    ev = result[1]
                    log_h = max(1, scr.getmaxyx()[0] - banner_h)
                    if ev['is_wheel']:
                        max_offset = _sync_pin(log_h)
                        step = 3
                        if ev['wheel_dir'] == 'up':
                            view_offset = min(max_offset, view_offset + step)
                        else:
                            view_offset = max(0, view_offset - step)
                    elif ev['button'] == 0 and not ev['is_motion'] and not ev['is_release']:
                        # Left-button press: starts a new selection (or, if this turns out
                        # to be a plain click with no drag, clears any existing one at
                        # release below) — matches native "click elsewhere deselects".
                        _sync_pin(log_h)
                        pos = _screen_to_content(ev['row'], ev['col'])
                        if pos is not None:
                            sel_anchor = pos
                            sel_cursor = pos
                            mouse_down = True
                        else:
                            sel_anchor = None
                            sel_cursor = None
                            mouse_down = False
                    elif ev['is_motion']:
                        if mouse_down:
                            _sync_pin(log_h)
                            pos = _screen_to_content(ev['row'], ev['col'])
                            if pos is not None:
                                sel_cursor = pos
                    elif ev['is_release']:
                        if mouse_down:
                            mouse_down = False
                            _sync_pin(log_h)
                            if sel_anchor is not None and sel_cursor is not None and sel_anchor != sel_cursor:
                                # A real drag: auto-copy on release, X11-primary-selection
                                # style — no keychord required. Both paths are tried: OSC 52
                                # (works over SSH/tmux-passthrough, but unsupported outright
                                # on some VTE-based terminals — Terminator confirmed) and a
                                # local clipboard CLI tool if one's installed (reaches the
                                # real clipboard directly, but only on a local X11/Wayland
                                # session) — see the module docstring's "Mouse selection"
                                # paragraph.
                                lo_offset, _, hi_offset, _ = _selection_bounds(sel_anchor, sel_cursor)
                                sel_rows = ring.visible_rows(lo_offset, hi_offset - lo_offset + 1)
                                text = extract_selection_text(sel_rows, sel_anchor, sel_cursor)
                                if text:
                                    copy_via_system_clipboard_tool(text)
                                    try:
                                        os.write(1, build_osc52_sequence(text))
                                    except OSError:
                                        pass
                                    # Shown unconditionally once an attempt was made through
                                    # both paths -- neither actually confirms clipboard
                                    # ownership was established (OSC 52 has no ack, and a
                                    # local tool "not raising" isn't proof either, e.g. no
                                    # DISPLAY), so like most terminals' own copy indicators
                                    # this reflects "the action was taken", not a verified
                                    # outcome.
                                    copy_toast_state['at'] = time.monotonic()
                            else:
                                # Plain click (no drag) — clear any selection.
                                sel_anchor = None
                                sel_cursor = None
                    # Middle/right-click (button 1/2) and stray motion with no button held
                    # are intentionally no-ops — see the module docstring.
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
