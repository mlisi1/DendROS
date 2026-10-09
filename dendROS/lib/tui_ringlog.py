"""RingLog: the TUI launch mode's bounded scrollback — pure, curses-free, unit-tested in
test/unit/test_launch_tui.py. Split out of lib/tui_pure.py to keep that file sized; it's
the one stateful piece of the TUI's pure layer (wrapping, filtering, seq identity, and the
tail-growth/anchor bookkeeping that keeps a scrolled-back view on its content).
"""

import collections
import threading

from lib.tui_pure import wrap_line


class RingLog:
    """Bounded scrollback: (segments, plain_text, node_name, logger_name) tuples. `_lines`
    is the sole source of truth — nothing is projected onto a persistent curses pad;
    visible_rows()/set_width() wrap on demand for whatever's actually visible, so a resize
    is just "wrap differently next redraw" with no replay step. append() runs from both the
    main thread (queue drain) and the reader thread (during a disable gap), so mutating
    methods take a lock.

    node_name/logger_name (both optional, default None) are the launch process tag / ROS
    graph logger name already discovered upstream by dendROS_pipe.py's own colorization
    pipeline (see its _colorize() docstring) — RingLog just carries them alongside each
    line so lib/console_commands.py's node-identity filtering never has to reverse-parse
    them back out of the (config-dependent, ambiguous) rendered text.
    """

    def __init__(self, maxlen):
        self.maxlen = maxlen
        self._lines = collections.deque(maxlen=maxlen)
        self._row_counts = collections.deque(maxlen=maxlen)
        self._wrap_width = None
        self._total_rows = 0
        self._lock = threading.Lock()
        self._filter_fn = None          # Optional[Callable[[str, str, str], bool]]:
                                         # (plain_text, node_name, logger_name) -> bool
        self._filtered_total_rows = 0   # maintained in parallel to _total_rows while active
        self._seq = 0                   # lines ever appended; _lines[i]'s seq = _seq - len + i
        self._tail_growth = 0           # rows ever appended that passed the filter at append
                                         # time — see tail_growth()

    def __len__(self):
        return len(self._lines)

    def __getitem__(self, idx):
        return self._lines[idx]

    def plain_lines(self):
        return [plain for _, plain, _, _ in self._lines]

    def entries(self):
        """Locked snapshot of every retained (segments, plain_text, node_name, logger_name)
        tuple, oldest-first, ignoring any filter — used to persist the run for
        `dendros reopen` (lib/tui_history.py) while the reader thread may still append."""
        with self._lock:
            return list(self._lines)

    def node_identities(self):
        """(node_name, logger_name) for every retained line, oldest-first — used to seed
        the TUI's known-nodes set from history already in the ring (see
        lib/launch_tui_console.py's _build_known_nodes_from_ring())."""
        return [(node_name, logger_name) for _, _, node_name, logger_name in self._lines]

    def seq_range(self):
        """(first, end) seq numbers of retained lines, end exclusive. A seq is a line's
        permanent identity (eviction/rewrap/filtering never renumber it) — used by
        lib/tui_find.py to keep pointing at the same match as the ring changes."""
        return self._seq - len(self._lines), self._seq

    def visible_entries(self):
        """Snapshot of (seq, row_count, plain_text) for every line passing the active
        filter, oldest-first — the same lines, in the same order, visible_rows() draws."""
        with self._lock:
            base = self._seq - len(self._lines)
            return [
                (base + i, rc, plain)
                for i, (rc, (_, plain, node_name, logger_name)) in enumerate(zip(self._row_counts, self._lines))
                if self._filter_fn is None or self._filter_fn(plain, node_name, logger_name)
            ]

    def set_filter(self, predicate):
        """Set (or clear, with None) a presentation-only filter. `predicate(plain_text,
        node_name, logger_name) -> bool`. Never touches _lines/_row_counts — the full
        unfiltered history is always retained, so clearing the filter restores everything,
        including lines appended while it was active. Recomputes _filtered_total_rows in
        one O(history) pass, bounded by the scrollback's maxlen."""
        with self._lock:
            self._filter_fn = predicate
            if predicate is None:
                self._filtered_total_rows = 0
                return
            self._filtered_total_rows = sum(
                rc for rc, (_, plain, node_name, logger_name) in zip(self._row_counts, self._lines)
                if predicate(plain, node_name, logger_name)
            )

    def append(self, segments, plain_text, node_name=None, logger_name=None):
        with self._lock:
            evicted_rows = 0
            evicted = None
            if self.maxlen is not None and len(self._lines) == self.maxlen:
                evicted_rows = self._row_counts[0]
                evicted = self._lines[0]
            self._lines.append((segments, plain_text, node_name, logger_name))
            self._seq += 1
            row_count = len(wrap_line(segments, self._wrap_width)) if self._wrap_width else 1
            self._row_counts.append(row_count)
            self._total_rows += row_count - evicted_rows

            if self._filter_fn is not None:
                if evicted is not None and self._filter_fn(evicted[1], evicted[2], evicted[3]):
                    self._filtered_total_rows -= evicted_rows
                if self._filter_fn(plain_text, node_name, logger_name):
                    self._filtered_total_rows += row_count
                    self._tail_growth += row_count
            else:
                self._tail_growth += row_count

    def set_width(self, width):
        """Rewrap all retained history at a new width. No-op if unchanged — the only
        O(history) operation, and only runs once per actual resize."""
        width = max(1, width)
        with self._lock:
            if width == self._wrap_width:
                return
            self._wrap_width = width
            self._row_counts = collections.deque(
                (len(wrap_line(segments, width)) for segments, _, _, _ in self._lines),
                maxlen=self.maxlen,
            )
            self._total_rows = sum(self._row_counts)
            if self._filter_fn is not None:
                self._filtered_total_rows = sum(
                    rc for rc, (_, plain, node_name, logger_name) in zip(self._row_counts, self._lines)
                    if self._filter_fn(plain, node_name, logger_name)
                )

    @property
    def wrap_width(self):
        return self._wrap_width

    def tail_growth(self):
        """Cumulative count of visible rows ever appended at the tail. A tail-relative
        position (a scrolled-back view, a selection) must shift by exactly the growth of
        this counter to stay on the same content — *not* by the change in total_rows(),
        which also drops as old lines are evicted from a full scrollback, and changes on a
        rewrap or filter change where nothing was appended at all."""
        return self._tail_growth

    def _visible_newest_first(self):
        # (seq, row_count) of lines passing the filter, newest-first. Caller holds the lock.
        base = self._seq - len(self._lines)
        for i in range(len(self._lines) - 1, -1, -1):
            _, plain, node_name, logger_name = self._lines[i]
            if self._filter_fn is None or self._filter_fn(plain, node_name, logger_name):
                yield base + i, self._row_counts[i]

    def anchor_at(self, offset):
        """(seq, row_in_line) of the visible row `offset` rows back from the tail (0 = the
        newest row), or None if there's no such row. Pairs with offset_of() to keep a view
        on the same content across a rewrap (set_width())."""
        offset = max(0, offset)
        with self._lock:
            seen = 0
            for seq, rc in self._visible_newest_first():
                if offset < seen + rc:
                    return seq, rc - 1 - (offset - seen)
                seen += rc
            return None

    def offset_of(self, seq, row_in_line):
        """Tail offset of row `row_in_line` of line `seq` under the current wrap width and
        filter — row_in_line is clamped to the line's (possibly fewer) rows. None if the line
        was evicted or is hidden by the filter."""
        with self._lock:
            seen = 0
            for s, rc in self._visible_newest_first():
                if s == seq:
                    return seen + rc - 1 - max(0, min(row_in_line, rc - 1))
                if s < seq:
                    return None
                seen += rc
            return None

    def total_rows(self):
        return self._filtered_total_rows if self._filter_fn is not None else self._total_rows

    def visible_rows(self, view_offset, height):
        """Up to `height` (segments, is_continuation) rows ending `view_offset` rows back
        from the tail. is_continuation marks a mid-line wrap (vs. a new logical line), so
        callers can rejoin text without spurious newlines. Also usable for an arbitrary
        historical range, not just the live viewport.

        When a filter is active (set_filter()), non-matching lines are skipped entirely —
        this is presentation-only, _lines itself is never touched."""
        with self._lock:
            width = self._wrap_width or 1
            height = max(0, height)
            view_offset = max(0, view_offset)
            need = view_offset + height
            collected_rev = []  # (segments, is_continuation), newest-first while accumulating
            for segments, plain, node_name, logger_name in reversed(self._lines):
                if len(collected_rev) >= need:
                    break
                if self._filter_fn is not None and not self._filter_fn(plain, node_name, logger_name):
                    continue
                wrapped = wrap_line(segments, width)
                tagged = [(row, i > 0) for i, row in enumerate(wrapped)]
                collected_rev.extend(reversed(tagged))
            collected_rev.reverse()
            end = max(0, len(collected_rev) - view_offset)
            start = max(0, end - height)
            return collected_rev[start:end]
