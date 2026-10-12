"""`\\help` overlay for lib/launch_tui.py's `_TuiSession` (mixed in there as `_TuiHelpMixin`).

The help panel is the only thing allowed to draw over the log body: a brand-colored box
(orange on brand blue, same colors as the console bar) centered over the scrollback,
listing every console command and key. Content comes from lib/console_spec.py (shared with
Tab completion), laid out by its pure help_rows(). While it's open it captures all keys:
Up/Down/PageUp/PageDown/Home/End and the mouse wheel scroll it, Esc/q/\\ close it. It is
not part of the Esc mode stack — Esc closes it before touching any filter.

Curses-owning like the other mixins — manual-testing only.
"""

from lib.console_spec import help_rows
from lib.launch_tui_input import read_escape_sequence

_HELP_MAX_INNER_W = 92
_HELP_TITLE = ' dendROS console help '


class _TuiHelpMixin:

    def _init_help_state(self):
        self.help_open = False
        self.help_offset = 0   # first content row shown (scrolled down by N rows)

    def _cmd_help(self, arg):
        self.help_open = True
        self.help_offset = 0
        self.console_error = None
        return True

    def _help_close(self):
        self.help_open = False

    def _help_geometry(self):
        """(top, left, box_h, box_w, inner_w, view_h, rows) for the current screen size."""
        max_y, max_x = self.scr.getmaxyx()
        log_h = self._log_height(max_y)
        usable_width = max(1, max_x - 2)  # same body width as _redraw(); scrollbar stays visible
        box_w = min(usable_width, _HELP_MAX_INNER_W + 4)
        inner_w = max(1, box_w - 4)       # border + 1 column of padding each side
        rows = help_rows(inner_w)
        box_h = min(log_h, len(rows) + 2)
        view_h = max(0, box_h - 2)
        top = self.banner_h + (log_h - box_h) // 2
        left = (usable_width - box_w) // 2
        return top, left, box_h, box_w, inner_w, view_h, rows

    def _help_scroll(self, delta):
        _, _, _, _, _, view_h, rows = self._help_geometry()
        max_off = max(0, len(rows) - view_h)
        self.help_offset = max(0, min(max_off, self.help_offset + delta))

    def _help_key(self, ch):
        if ch in (ord('q'), ord('\\')):
            self._help_close()
            return
        if ch != 27:
            return  # everything else is swallowed while the panel is up
        result = read_escape_sequence(self.scr, self.curses)
        if result is None:
            return
        kind, payload = result
        if kind == 'escape':
            self._help_close()
        elif kind == 'nav':
            view_h = self._help_geometry()[5]
            step = {'up': -1, 'down': 1, 'page_up': -max(1, view_h - 1),
                    'page_down': max(1, view_h - 1), 'home': -10 ** 6, 'end': 10 ** 6}.get(payload)
            if step:
                self._help_scroll(step)
        elif kind == 'mouse' and payload['is_wheel']:
            self._help_scroll(-3 if payload['wheel_dir'] == 'up' else 3)

    def _draw_help(self):
        curses = self.curses
        scr = self.scr
        top, left, box_h, box_w, inner_w, view_h, rows = self._help_geometry()
        if box_h < 3 or box_w < 8:
            return
        max_off = max(0, len(rows) - view_h)
        self.help_offset = min(self.help_offset, max_off)  # e.g. after a resize

        orange = self.pair_cache.attr_for(self.console_fg, self.console_bg, False)
        styles = {
            'section': orange | curses.A_BOLD,
            'key': self.pair_cache.attr_for(None, self.console_bg, True),
            'desc': self.pair_cache.attr_for(None, self.console_bg, False),
            'note': orange,
        }
        fill = self.pair_cache.attr_for(None, self.console_bg, False)

        def put(y, x, text, attr):
            try:
                scr.addstr(y, x, text, attr)
            except curses.error:
                pass

        # Border, with the title on the top edge and a scroll/close hint on the bottom one.
        put(top, left, '╭' + '─' * (box_w - 2) + '╮', orange)
        title = _HELP_TITLE[:box_w - 4]
        put(top, left + (box_w - len(title)) // 2, title, orange | curses.A_BOLD)
        footer = ' ↑↓ scroll · Esc close ' if max_off else ' Esc close '
        footer = footer[:box_w - 4]
        put(top + box_h - 1, left, '╰' + '─' * (box_w - 2) + '╯', orange)
        put(top + box_h - 1, left + box_w - 2 - len(footer), footer, orange)

        for i in range(view_h):
            y = top + 1 + i
            put(y, left, '│', orange)
            put(y, left + 1, ' ' * (box_w - 2), fill)
            put(y, left + box_w - 1, '│', orange)
            idx = self.help_offset + i
            if idx >= len(rows):
                continue
            x = left + 2
            for text, style in rows[idx]:
                text = text[:max(0, left + 2 + inner_w - x)]
                put(y, x, text, styles[style])
                x += len(text)
