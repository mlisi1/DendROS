"""`\\find <text>` handling for lib/launch_tui.py's `_TuiSession` (mixed in there as
`_TuiFindMixin`, alongside the render/console/input mixins).

Split out like the other mixins: a cohesive group of methods over `_TuiSession`'s own state,
in its own file to keep file sizes manageable. Curses-owning — manual-testing only; the pure
matching/stepping/offset math lives in lib/tui_find.py and is unit-tested there.

User-facing behavior: `\\find <text>` jumps to the newest match at or above the bottom of the
view and centers it; Tab steps to older matches, Shift+Tab to newer ones (wrapping); all
matches on screen are highlighted, the current line's in brand orange; a `find "text" n/N`
indicator sits in the header. A find *freezes* the view (find_pinned) so streaming output
can't scroll the match away — End, or scrolling back down to the tail, resumes following.
Esc (console closed) ends the find; `\\clear` ends it along with any focus filter.
"""

from lib.tui_find import (
    center_view_offset,
    find_matching_seqs,
    format_find_status,
    initial_match_seq,
    line_tail_offsets,
    match_position,
    rows_meta,
    step_match_seq,
)


class _TuiFindMixin:

    def _init_find_state(self):
        self.find_query = None      # active search text, or None
        self.find_seq = None        # RingLog seq of the current match line
        self.find_pinned = False    # True = view frozen on the match (see module docstring)
        self._find_cache_key = None
        self._find_cache = []

    def _find_matches(self):
        # Recomputed only when the ring's contents, the focus filter, or the query change —
        # i.e. at most once per drained tick while a find is active.
        key = (self.ring.seq_range(), self.filter_node, self.find_query)
        if key != self._find_cache_key:
            self._find_cache = find_matching_seqs(self.ring.visible_entries(), self.find_query)
            self._find_cache_key = key
        return self._find_cache

    def _find_status(self):
        if self.find_query is None:
            return None
        matches = self._find_matches()
        return format_find_status(self.find_query, match_position(matches, self.find_seq), len(matches))

    def _find_jump(self, seq):
        offsets = line_tail_offsets(self.ring.visible_entries(), seq)
        if offsets is None:
            return
        log_h = self._log_height(self.scr.getmaxyx()[0])
        max_offset = self._sync_pin(log_h)  # re-baseline before moving view_offset
        self.find_seq = seq
        self.view_offset = center_view_offset(offsets[0], log_h, max_offset)
        self.find_pinned = True

    def _find_step(self, direction):
        if self.find_query is None:
            return
        seq = step_match_seq(self._find_matches(), self.find_seq, direction)
        if seq is not None:
            self._find_jump(seq)

    def _find_clear(self):
        self._init_find_state()

    def _find_release_pin_if_at_tail(self):
        # Scrolling back down to the live tail means "follow again", same as End.
        if self.view_offset == 0:
            self.find_pinned = False

    def _find_after_filter_change(self):
        # A focus change re-scopes the search to the newly visible lines: stay on the
        # current match if it's still visible, else move to the nearest older one.
        if self.find_query is None:
            return
        matches = self._find_matches()
        if self.find_seq in matches:
            self._find_jump(self.find_seq)
        elif matches:
            self._find_jump(step_match_seq(matches, self.find_seq, 'older'))
        else:
            self.find_pinned = False  # indicator shows -/0 until \clear or new matches

    def _find_render_rows(self, log_h):
        """(seq, row_in_line) per visible row plus {seq: plain_text} for those rows, or
        None when no find is active — see _redraw() in lib/launch_tui_render.py."""
        if self.find_query is None:
            return None
        entries = self.ring.visible_entries()
        meta = rows_meta(entries, self.view_offset, log_h)
        seqs = {seq for seq, _ in meta}
        plain_by_seq = {seq: plain for seq, _, plain in entries if seq in seqs}
        return meta, plain_by_seq

    def _cmd_find(self, arg):
        query = arg.strip()
        if not query:
            self._show_console_error('find: text required')
            return False
        entries = self.ring.visible_entries()
        matches = find_matching_seqs(entries, query)
        if not matches:
            self._show_console_error(f'find: no matches for "{query}"')
            return False
        log_h = self._log_height(self.scr.getmaxyx()[0])
        self._sync_pin(log_h)
        self.find_query = query
        self._find_cache_key = None
        self._find_jump(initial_match_seq(matches, entries, self.view_offset))
        self.console_error = None
        return True
