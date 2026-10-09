"""Curses drawing methods for lib/launch_tui.py's `_TuiSession` (mixed in there via
`_TuiRenderMixin`). Split out purely to keep launch_tui.py's session/event-loop code and
its rendering code in separate, independently-sized files — every method here still
depends on `_TuiSession`'s own state (self.scr, self.pair_cache, self.ring, self.view_offset,
etc.) and the two are one logical unit, not a reusable component.
"""

import time

from lib.launch_tui_console import (
    _TOAST_BOLD_UNTIL,
    _TOAST_NORMAL_UNTIL,
    _TOAST_DIM_UNTIL,
)
from lib.console_commands import MARK_FILL, MARK_ID
from lib.tui_find import row_highlight_spans
from lib.tui_pure import (
    segments_from_ansi,
    screen_row_to_tail_offset,
    selection_span_for_row,
    compute_scrollbar_thumb,
)

# "Copied" toast: fades with the shared _TOAST_*_UNTIL timings, curses' nearest
# approximation of a fade.
_COPY_TOAST_TEXT = 'Copied'

# Right-aligned header key hint, (key, description) pairs — context-dependent so the keys
# that matter right now are the ones advertised (see _header_key_hints()).
_HINT_IDLE = (('\\', 'open console'),)
_HINT_CONSOLE = (('Tab', 'complete'), ('↑↓', 'history'), ('Enter', 'run'), ('Esc', 'close'))
_HINT_FIND_STEP = ('Tab/S-Tab', 'step')
_HINT_HELP = (('Esc', 'close help'),)


def _hint_width(pairs):
    # "key desc" per pair, two spaces between pairs.
    return sum(len(k) + 1 + len(d) for k, d in pairs) + 2 * (len(pairs) - 1)


class _TuiRenderMixin:

    def _draw_segments(self, row, col, usable_width, segments, default_bg=None, sel_span=None,
                       find_spans=None, find_attr=None, grep_spans=None):
        # default_bg backfills segments with no bg of their own (e.g. header text); ones
        # that DO carry a bg (e.g. a crash-alert banner) keep it. find_spans: inclusive
        # (start, end) `\find` match columns — drawn with find_attr (the current match's
        # brand-orange chip) when given, else reverse video. grep_spans: `\grep` match
        # columns, drawn bold+underlined brand orange over the line's own background (like
        # `grep --color`; underline keeps it visible on an orange line). Find wins on overlap.
        curses = self.curses
        if sel_span is None and not find_spans and not grep_spans:
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

        # Highlight path: per-character, so the selection (A_REVERSE) can be OR'd onto
        # the normal attribute rather than replacing it.
        find_spans = find_spans or ()
        grep_spans = grep_spans or ()
        for seg_text, fg, bg, bold in segments:
            eff_bg = bg if bg is not None else default_bg
            base_attr = self.pair_cache.attr_for(fg, eff_bg, bold) if (fg is not None or eff_bg is not None or bold) else 0
            grep_attr = self.pair_cache.attr_for(self.console_fg, eff_bg, True) | curses.A_UNDERLINE
            for ch in seg_text:
                if col >= usable_width:
                    return col
                attr = base_attr
                if any(s <= col <= e for s, e in find_spans):
                    attr = find_attr if find_attr is not None else attr | curses.A_REVERSE
                elif any(s <= col <= e for s, e in grep_spans):
                    attr = grep_attr
                if sel_span is not None and sel_span[0] <= col <= sel_span[1]:
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
        left_end = alert_col  # first free column after the left-side content

        text = self.banner_text
        if not text:
            if self.review:
                hint = f'-- {self.review_label} -- q: quit  PageUp/PageDown: scroll --'
            elif self.eof:
                hint = '-- process finished -- q: quit  PageUp/PageDown: scroll --'
            elif self.clipboard_tool_missing:
                # Lowest-priority, idle-only hint — surfaces the copy limitation before a
                # drag rather than after.
                hint = '-- copy needs xclip/xsel/wl-copy (none found) --'
            else:
                hint = ''
            if hint:
                try:
                    scr.addstr(row, alert_col, hint[:max(0, usable_width - alert_col)], header_attr | curses.A_DIM)
                except curses.error:
                    pass
                left_end = alert_col + len(hint)
        else:
            left_end = self._draw_segments(row, alert_col, usable_width, segments_from_ansi(text),
                                           default_bg=self.header_bg)

        # Right side, right to left: key hint, then the find/filter chips. The key hint is the
        # lowest-priority header item — dropped rather than drawn over left-side content
        # (crash/param alerts, the process-finished hint).
        right_col = usable_width
        hints = self._header_key_hints()
        hint_w = _hint_width(hints)
        if right_col - hint_w - 1 >= left_end:
            right_col -= hint_w + 1
            self._draw_key_hints(row, right_col + 1, hints, header_attr)

        # Brand chips (same colors as the console bar), right to left: the find indicator,
        # then the active filter stack (focus/grep). The "Copied" toast briefly draws over
        # the rightmost one, which is fine for a 1.4s flash.
        # Then the mute count — plain bold orange text, not a chip: mute isn't a mode.
        chip_attr = self.pair_cache.attr_for(self.console_fg, self.console_bg, True)
        mute_attr = self.pair_cache.attr_for(self.console_fg, self.header_bg, True)
        for status, attr in ((self._find_status(), chip_attr), (self._filter_status(), chip_attr),
                             (self._mute_status(), mute_attr)):
            if status is None:
                continue
            chip = f' {status} '
            chip_col = max(alert_col, right_col - len(chip))
            try:
                scr.addstr(row, chip_col, chip[:max(0, right_col - chip_col)], attr)
            except curses.error:
                pass
            right_col = max(alert_col, chip_col - 1)

        copied_at = self.copy_toast_at
        if copied_at is not None:
            elapsed = time.monotonic() - copied_at
            if elapsed < _TOAST_BOLD_UNTIL:
                toast_attr = header_attr | curses.A_BOLD
            elif elapsed < _TOAST_NORMAL_UNTIL:
                toast_attr = header_attr
            elif elapsed < _TOAST_DIM_UNTIL:
                toast_attr = header_attr | curses.A_DIM
            else:
                toast_attr = None  # fully faded -- main loop clears copy_toast_at, not us
            if toast_attr is not None:
                msg_col = max(alert_col, usable_width - len(_COPY_TOAST_TEXT))
                try:
                    scr.addstr(row, msg_col, _COPY_TOAST_TEXT[:max(0, usable_width - msg_col)], toast_attr)
                except curses.error:
                    pass

    def _header_key_hints(self):
        if self.help_open:
            return _HINT_HELP
        if self.console_active:
            return _HINT_CONSOLE
        if not self.mode_stack:
            return _HINT_IDLE
        # Esc names the mode it will exit (the most recent one) — see _escape_mode().
        step = (_HINT_FIND_STEP,) if self.find_query is not None else ()
        return step + (('Esc', f'exit {self.mode_stack[-1]}'),)

    def _draw_key_hints(self, row, col, pairs, header_attr):
        # Keys bold, descriptions dim — reads as "press this" at a glance.
        curses = self.curses
        for i, (key, desc) in enumerate(pairs):
            for text, attr in ((key, header_attr | curses.A_BOLD), (' ' + desc, header_attr | curses.A_DIM)):
                try:
                    self.scr.addstr(row, col, text, attr)
                except curses.error:
                    pass
                col += len(text)
            if i < len(pairs) - 1:
                col += 2

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

        # Ambiguous Tab completion: candidates listed dim after the input, the one cycled
        # to (if any) in bold reverse. Cut off at the bar's edge.
        col = len(prompt) + 2
        cand_attr = self.pair_cache.attr_for(None, self.console_bg, False) | curses.A_DIM
        for i, cand in enumerate(self.completer.candidates):
            if col >= usable_width:
                break
            text = cand.strip()[:usable_width - col]
            attr = (console_attr | curses.A_REVERSE) if i == self.completer.index else cand_attr
            try:
                scr.addstr(row, col, text, attr)
            except curses.error:
                pass
            col += len(text) + 2

        if self.console_error is not None:
            elapsed = time.monotonic() - self.console_error_at
            error_attr = self.pair_cache.attr_for(curses.COLOR_RED, self.console_bg, False)
            if elapsed < _TOAST_BOLD_UNTIL:
                err_attr = error_attr | curses.A_BOLD
            elif elapsed < _TOAST_NORMAL_UNTIL:
                err_attr = error_attr
            elif elapsed < _TOAST_DIM_UNTIL:
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

    def _rewrap_keeping_view(self, width, log_h):
        # A resize rewraps all history, so every tail-relative row offset now points at
        # different content. Re-anchor by line instead: remember which (seq, row-in-line)
        # sits on the view's bottom row, rewrap, and put that line back there. A pinned find
        # is simply re-centered on its match. The selection's columns don't survive a
        # rewrap either, so it's dropped (the terminal-native equivalent loses it too).
        self._sync_pin(log_h)  # absorb pending appends before re-anchoring
        anchor = self.ring.anchor_at(self.view_offset) if self.view_offset > 0 else None
        self.ring.set_width(width)
        self.sel_anchor = None
        self.sel_cursor = None
        self.mouse_down = False
        self.last_tail_growth = self.ring.tail_growth()
        if anchor is not None:
            offset = self.ring.offset_of(*anchor)
            self.view_offset = offset if offset is not None else 0
        if self.find_pinned and self.find_seq is not None:
            self._find_jump(self.find_seq)

    def _redraw(self):
        curses = self.curses
        scr = self.scr
        max_y, max_x = scr.getmaxyx()
        log_h = self._log_height(max_y)
        # usable_width leaves one column for the scrollbar plus one never-written column
        # (a known curses trouble spot at the bottom-right cell).
        usable_width = max(1, max_x - 2)

        if usable_width != self.ring.wrap_width:
            self._rewrap_keeping_view(usable_width, log_h)
        self._sync_pin(log_h)

        self._draw_banner(max_x)
        # bkgdset() applies window-wide, not just to row 0 — reset before the body so
        # blank cells don't paint black instead of the terminal's real background.
        try:
            scr.bkgdset(' ', 0)
        except curses.error:
            pass

        rows = self.ring.visible_rows(self.view_offset, log_h, with_logger=True)
        mark_attr = self.pair_cache.attr_for(self.console_fg, self.console_bg, True)
        n_rows = len(rows)
        hl_rows = self._highlight_rows(log_h)  # None unless a `\find` or `\grep` is active
        current_find_attr = self.pair_cache.attr_for(0, self.console_fg, True)  # black on brand orange
        row_i = 0
        for wrapped_row, _is_continuation, logger_name in rows:
            scr_row = self.banner_h + row_i
            row_tail_offset = screen_row_to_tail_offset(row_i, n_rows, self.view_offset)
            row_len = sum(len(seg[0]) for seg in wrapped_row)
            sel_span = selection_span_for_row(row_tail_offset, row_len, self.sel_anchor, self.sel_cursor)
            find_spans = find_attr = grep_spans = None
            if hl_rows is not None and row_i < len(hl_rows[0]):
                seq, row_in_line = hl_rows[0][row_i]
                plain = hl_rows[1][seq]
                if self.find_query is not None:
                    find_spans = row_highlight_spans(plain, self.find_query, row_in_line,
                                                     usable_width, row_len)
                    if seq == self.find_seq:
                        find_attr = current_find_attr
                if self.grep_query is not None:
                    grep_spans = row_highlight_spans(plain, self.grep_query, row_in_line,
                                                     usable_width, row_len)
            try:
                scr.move(scr_row, 0)
                scr.clrtoeol()
            except curses.error:
                pass
            end_col = self._draw_segments(scr_row, 0, usable_width, wrapped_row, sel_span=sel_span,
                                          find_spans=find_spans, find_attr=find_attr,
                                          grep_spans=grep_spans)
            if logger_name == MARK_ID and end_col < usable_width:
                # `mark` rule: extended to the current width at draw time (not stored), so
                # it spans the screen at any terminal size. Not part of the line's text, so
                # selection/copy and find ignore it.
                try:
                    scr.addstr(scr_row, end_col, MARK_FILL * (usable_width - end_col), mark_attr)
                except curses.error:
                    pass
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
        if self.help_open:
            self._draw_help()  # the only thing allowed over the body — see lib/launch_tui_help.py
        if self._console_h():
            self._draw_console(max_x)

        scr.noutrefresh()
        curses.doupdate()
