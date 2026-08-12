"""Mouse/keyboard input handling for lib/launch_tui.py's `_TuiSession` (mixed in there as
`_TuiInputMixin`, alongside `_TuiRenderMixin` and `_TuiConsoleMixin`).

Split out for the same reason those two were: a cohesive group of methods that still
depends on `_TuiSession`'s own state, pulled into its own file purely to keep file sizes
manageable. Curses-owning like the rest of `_TuiSession` — manual-testing only. The pure
escape-sequence *decoding* (`decode_sgr_mouse`/`decode_navigation_key`) lives in
lib/tui_pure.py and is unit-tested there; this module is the curses-owning glue around it
(reading raw bytes off `scr.getch()`, translating a resolved event into view/selection state
changes).
"""

import os
import time

from lib.tui_pure import (
    _selection_bounds,
    screen_row_to_tail_offset,
    extract_selection_text,
    decode_sgr_mouse,
    decode_navigation_key,
    build_osc52_sequence,
    copy_via_system_clipboard_tool,
)

_MAX_SGR_PROBE_BYTES = 32  # generous for "Cb;Cx;Cy" decimal digits; bounds a malformed burst


def read_escape_sequence(scr, curses):
    # Called after getch() returns 27 (ESC). Decodes an SGR mouse report or a nav key off
    # the raw byte stream; returns ('mouse', event_dict), ('nav', action), or None (bare
    # Escape/unrecognized — probe byte pushed back via ungetch() so a standalone Escape
    # isn't lost).
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
                return None  # incomplete/malformed -- drop silently
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


class _TuiInputMixin:

    def _screen_to_content(self, mouse_row, mouse_col):
        # Maps a clicked/dragged screen cell to a content-relative (offset, col), mirroring
        # _redraw()'s row loop. Caller must have just called _sync_pin().
        max_y, max_x = self.scr.getmaxyx()
        log_h = self._log_height(max_y)
        usable_width = max(1, max_x - 2)  # scrollbar column + one reserved buffer — see _redraw()
        body_row = mouse_row - self.banner_h
        if body_row < 0:
            return None  # click landed on the header row
        rows = self.ring.visible_rows(self.view_offset, log_h)
        n_rows = len(rows)
        if n_rows == 0:
            return None
        if body_row >= n_rows:
            body_row = n_rows - 1  # clicked in blank padding below content
        row_tail_offset = screen_row_to_tail_offset(body_row, n_rows, self.view_offset)
        segments, _is_continuation = rows[body_row]
        row_len = sum(len(seg[0]) for seg in segments)
        col = max(0, min(mouse_col, usable_width - 1))
        col = min(col, max(0, row_len - 1) if row_len else 0)
        return (row_tail_offset, col)

    def _handle_mouse(self, ev):
        log_h = self._log_height(self.scr.getmaxyx()[0])
        if ev['is_wheel']:
            max_offset = self._sync_pin(log_h)
            step = 3
            if ev['wheel_dir'] == 'up':
                self.view_offset = min(max_offset, self.view_offset + step)
            else:
                self.view_offset = max(0, self.view_offset - step)
        elif ev['button'] == 0 and not ev['is_motion'] and not ev['is_release']:
            # Left-button press: starts a new selection (native "click elsewhere
            # deselects" is handled on release below).
            self._sync_pin(log_h)
            pos = self._screen_to_content(ev['row'], ev['col'])
            if pos is not None:
                self.sel_anchor = pos
                self.sel_cursor = pos
                self.mouse_down = True
            else:
                self.sel_anchor = None
                self.sel_cursor = None
                self.mouse_down = False
        elif ev['is_motion']:
            if self.mouse_down:
                self._sync_pin(log_h)
                pos = self._screen_to_content(ev['row'], ev['col'])
                if pos is not None:
                    self.sel_cursor = pos
        elif ev['is_release']:
            if self.mouse_down:
                self.mouse_down = False
                self._sync_pin(log_h)
                if self.sel_anchor is not None and self.sel_cursor is not None and self.sel_anchor != self.sel_cursor:
                    # Real drag: auto-copy on release via both OSC 52 and a local
                    # clipboard tool (see lib/launch_tui.py's module docstring).
                    lo_offset, _, hi_offset, _ = _selection_bounds(self.sel_anchor, self.sel_cursor)
                    sel_rows = self.ring.visible_rows(lo_offset, hi_offset - lo_offset + 1)
                    text = extract_selection_text(sel_rows, self.sel_anchor, self.sel_cursor)
                    if text:
                        copy_via_system_clipboard_tool(text)
                        try:
                            os.write(1, build_osc52_sequence(text))
                        except OSError:
                            pass
                        self.copy_toast_at = time.monotonic()
                else:
                    self.sel_anchor = None  # plain click (no drag) — clear selection
                    self.sel_cursor = None
        # Middle/right-click and stray motion with no button held: no-ops.

    def _handle_nav(self, action):
        if action not in ('page_up', 'page_down', 'home', 'end', 'up', 'down'):
            return  # 'left'/'right' intentionally unbound
        log_h = self._log_height(self.scr.getmaxyx()[0])
        max_offset = self._sync_pin(log_h)
        if action == 'page_up':
            self.view_offset = min(max_offset, self.view_offset + log_h)
        elif action == 'page_down':
            self.view_offset = max(0, self.view_offset - log_h)
        elif action == 'home':
            self.view_offset = max_offset
        elif action == 'end':
            self.view_offset = 0
        elif action == 'up':
            self.view_offset = min(max_offset, self.view_offset + 1)
        elif action == 'down':
            self.view_offset = max(0, self.view_offset - 1)
