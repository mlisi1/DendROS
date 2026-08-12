"""Curses drawing methods for lib/launch_tui.py's `_TuiSession` (mixed in there via
`_TuiRenderMixin`). Split out purely to keep launch_tui.py's session/event-loop code and
its rendering code in separate, independently-sized files — every method here still
depends on `_TuiSession`'s own state (self.scr, self.pair_cache, self.ring, self.view_offset,
etc.) and the two are one logical unit, not a reusable component.
"""

import time

from lib.launch_tui_console import (
    _CONSOLE_ERROR_BOLD_UNTIL,
    _CONSOLE_ERROR_NORMAL_UNTIL,
    _CONSOLE_ERROR_DIM_UNTIL,
)
from lib.tui_pure import (
    segments_from_ansi,
    screen_row_to_tail_offset,
    selection_span_for_row,
    compute_scrollbar_thumb,
)

# "Copied" toast: bold -> normal -> dim -> gone, curses' nearest approximation of a fade.
_COPY_TOAST_TEXT = 'Copied'
_COPY_TOAST_BOLD_UNTIL = 1.2
_COPY_TOAST_NORMAL_UNTIL = 1.3
_COPY_TOAST_DIM_UNTIL = 1.4


class _TuiRenderMixin:

    def _draw_segments(self, row, col, usable_width, segments, default_bg=None, sel_span=None):
        # default_bg backfills segments with no bg of their own (e.g. header text); ones
        # that DO carry a bg (e.g. a crash-alert banner) keep it.
        curses = self.curses
        if sel_span is None:
            # Fast path: one addstr() per same-attr run.
            for seg_text, fg, bg, bold in segments:
                if col >= usable_width:
                    break
                eff_bg = bg if bg is not None else default_bg
                attr = self.pair_cache.attr_for(fg, eff_bg, bold) if (fg is not None or eff_bg is not None or bold) else 0
                try:
                    self.scr.addstr(row, col, seg_text[:max(0, usable_width - col)], attr)
                except curses.error:
                    pass
                col += len(seg_text)
            return col

        # Selection path: per-character, so the highlight (A_REVERSE) can be OR'd onto
        # the normal attribute rather than replacing it.
        for seg_text, fg, bg, bold in segments:
            eff_bg = bg if bg is not None else default_bg
            base_attr = self.pair_cache.attr_for(fg, eff_bg, bold) if (fg is not None or eff_bg is not None or bold) else 0
            for ch in seg_text:
                if col >= usable_width:
                    return col
                attr = base_attr
                if sel_span[0] <= col <= sel_span[1]:
                    attr |= curses.A_REVERSE
                try:
                    self.scr.addstr(row, col, ch, attr)
                except curses.error:
                    pass
                col += 1
        return col

    def _draw_banner(self, width):
        curses = self.curses
        scr = self.scr
        usable_width = max(0, width - 1)  # never write to the last column — see _redraw()
        row = 0

        header_attr = self.pair_cache.attr_for(None, self.header_bg, False)
        try:
            scr.bkgdset(' ', header_attr)
        except curses.error:
            pass
        scr.move(row, 0)
        scr.clrtoeol()

        col = self._draw_segments(row, 0, usable_width, self.header_segments, default_bg=self.header_bg)
        try:
            scr.addstr(row, col, self.version_text[:max(0, usable_width - col)], header_attr | curses.A_DIM)
        except curses.error:
            pass
        col += len(self.version_text)
        alert_col = min(usable_width, col + 1)

        text = self.banner_text
        if not text:
            if self.eof:
                hint = '-- process finished -- q: quit  PageUp/PageDown: scroll --'
                try:
                    scr.addstr(row, alert_col, hint[:max(0, usable_width - alert_col)], header_attr | curses.A_DIM)
                except curses.error:
                    pass
            elif self.clipboard_tool_missing:
                # Lowest-priority, idle-only hint — surfaces the copy limitation before a
                # drag rather than after.
                hint = '-- copy needs xclip/xsel/wl-copy (none found) --'
                try:
                    scr.addstr(row, alert_col, hint[:max(0, usable_width - alert_col)], header_attr | curses.A_DIM)
                except curses.error:
                    pass
        else:
            self._draw_segments(row, alert_col, usable_width, segments_from_ansi(text), default_bg=self.header_bg)

        copied_at = self.copy_toast_at
        if copied_at is not None:
            elapsed = time.monotonic() - copied_at
            if elapsed < _COPY_TOAST_BOLD_UNTIL:
                toast_attr = header_attr | curses.A_BOLD
            elif elapsed < _COPY_TOAST_NORMAL_UNTIL:
                toast_attr = header_attr
            elif elapsed < _COPY_TOAST_DIM_UNTIL:
                toast_attr = header_attr | curses.A_DIM
            else:
                toast_attr = None  # fully faded -- main loop clears copy_toast_at, not us
            if toast_attr is not None:
                msg_col = max(alert_col, usable_width - len(_COPY_TOAST_TEXT))
                try:
                    scr.addstr(row, msg_col, _COPY_TOAST_TEXT[:max(0, usable_width - msg_col)], toast_attr)
                except curses.error:
                    pass

    def _draw_console(self, width):
        curses = self.curses
        scr = self.scr
        max_y, _ = scr.getmaxyx()
        row = max_y - 1
        usable_width = max(0, width - 1)

        console_attr = self.pair_cache.attr_for(self.console_fg, self.console_bg, True)  # bold input text
        try:
            scr.bkgdset(' ', self.pair_cache.attr_for(None, self.console_bg, False))
        except curses.error:
            pass
        scr.move(row, 0)
        scr.clrtoeol()

        prompt = '\\ ' + self.console_buffer
        try:
            scr.addstr(row, 0, prompt[:usable_width], console_attr)
        except curses.error:
            pass

        if self.console_error is not None:
            elapsed = time.monotonic() - self.console_error_at
            error_attr = self.pair_cache.attr_for(curses.COLOR_RED, self.console_bg, False)
            if elapsed < _CONSOLE_ERROR_BOLD_UNTIL:
                err_attr = error_attr | curses.A_BOLD
            elif elapsed < _CONSOLE_ERROR_NORMAL_UNTIL:
                err_attr = error_attr
            elif elapsed < _CONSOLE_ERROR_DIM_UNTIL:
                err_attr = error_attr | curses.A_DIM
            else:
                err_attr = None  # fully faded -- main loop clears console_error, not us
            if err_attr is not None:
                # Right-aligned at the far edge of the bar, clamped so it never overlaps
                # the prompt text on a narrow terminal or a long buffer.
                min_col = min(usable_width, len(prompt) + 2)
                err_col = max(min_col, usable_width - len(self.console_error))
                try:
                    scr.addstr(row, err_col, self.console_error[:max(0, usable_width - err_col)], err_attr)
                except curses.error:
                    pass

        try:
            scr.bkgdset(' ', 0)
        except curses.error:
            pass

    def _draw_scrollbar(self):
        # Self-contained so it can run alone (no full _redraw()) on ticks where the body
        # redraw is skipped to protect a pinned/selected view — the scrollbar has nothing
        # of its own to protect.
        curses = self.curses
        max_y, max_x = self.scr.getmaxyx()
        log_h = self._log_height(max_y)
        usable_width = max(1, max_x - 2)  # keep in sync with _redraw()/_screen_to_content()
        scrollbar_col = usable_width
        max_offset = self._sync_pin(log_h)
        thumb_start, thumb_height = compute_scrollbar_thumb(log_h, self.view_offset, max_offset,
                                                             self.ring.total_rows())
        for row_i in range(log_h):
            scr_row = self.banner_h + row_i
            try:
                if thumb_start <= row_i < thumb_start + thumb_height:
                    self.scr.addstr(scr_row, scrollbar_col, ' ', curses.A_REVERSE)
                else:
                    self.scr.addstr(scr_row, scrollbar_col, '│', curses.A_DIM)
            except curses.error:
                pass

    def _redraw(self):
        curses = self.curses
        scr = self.scr
        max_y, max_x = scr.getmaxyx()
        log_h = self._log_height(max_y)
        # usable_width leaves one column for the scrollbar plus one never-written column
        # (a known curses trouble spot at the bottom-right cell).
        usable_width = max(1, max_x - 2)

        self.ring.set_width(usable_width)  # no-op unless the terminal was actually resized
        self._sync_pin(log_h)

        self._draw_banner(max_x)
        # bkgdset() applies window-wide, not just to row 0 — reset before the body so
        # blank cells don't paint black instead of the terminal's real background.
        try:
            scr.bkgdset(' ', 0)
        except curses.error:
            pass

        rows = self.ring.visible_rows(self.view_offset, log_h)
        n_rows = len(rows)
        row_i = 0
        for wrapped_row, _is_continuation in rows:
            scr_row = self.banner_h + row_i
            row_tail_offset = screen_row_to_tail_offset(row_i, n_rows, self.view_offset)
            row_len = sum(len(seg[0]) for seg in wrapped_row)
            sel_span = selection_span_for_row(row_tail_offset, row_len, self.sel_anchor, self.sel_cursor)
            try:
                scr.move(scr_row, 0)
                scr.clrtoeol()
            except curses.error:
                pass
            self._draw_segments(scr_row, 0, usable_width, wrapped_row, sel_span=sel_span)
            row_i += 1
        while row_i < log_h:  # blank out rows below the last one drawn
            scr_row = self.banner_h + row_i
            try:
                scr.move(scr_row, 0)
                scr.clrtoeol()
            except curses.error:
                pass
            row_i += 1

        self._draw_scrollbar()  # real terminal scrollbar is inert on the alt screen buffer
        if self._console_h():
            self._draw_console(max_x)

        scr.noutrefresh()
        curses.doupdate()
