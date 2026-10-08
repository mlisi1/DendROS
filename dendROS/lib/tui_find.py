"""Pure, curses-free logic behind the TUI launch mode's `\\find <text>` console command (see
lib/launch_tui_find.py for the curses-owning side). Unit-tested directly
(test/unit/test_tui_find.py).

Model: a match is a whole *line* (like `less`), identified by its RingLog seq number
(RingLog.seq_range()/visible_entries()) — a permanent identity that eviction, rewrapping
and focus-filtering never renumber, so "the current match" stays the same line while new
output streams in. Matches are counted oldest-first, so a frozen view's counter reads e.g.
`17/19` when two newer matches have arrived below it. Tab steps to older matches and
Shift+Tab to newer ones, wrapping at either end.

Matching is a plain substring with smart case (case-insensitive unless the query has an
uppercase letter, as in vim/ripgrep), run against each line's displayed plain text — so
search sees exactly what's on screen (e.g. hidden timestamps aren't searchable).

`entries` everywhere below is RingLog.visible_entries()'s snapshot: (seq, row_count,
plain_text) for each line passing the active focus filter, oldest-first. Offsets are
tail-relative rows, the same units as RingLog.visible_rows()'s view_offset.
"""

import bisect


def is_case_sensitive(query):
    """Smart case: an uppercase letter anywhere in the query makes the match exact-case."""
    return any(c.isupper() for c in query)


def match_spans(text, query):
    """Non-overlapping (start, end_exclusive) occurrences of `query` in `text`, smart-case."""
    if not query:
        return []
    if not is_case_sensitive(query):
        text = text.lower()
        query = query.lower()
    spans = []
    start = text.find(query)
    while start != -1:
        spans.append((start, start + len(query)))
        start = text.find(query, start + len(query))
    return spans


def find_matching_seqs(entries, query):
    """Seqs of the lines containing `query`, oldest-first (sorted ascending)."""
    if not query:
        return []
    if is_case_sensitive(query):
        return [seq for seq, _, plain in entries if query in plain]
    q = query.lower()
    return [seq for seq, _, plain in entries if q in plain.lower()]


def line_tail_offsets(entries, seq):
    """(top_offset, bottom_offset) of line `seq`'s first/last wrapped rows, or None if the
    line isn't in `entries` (evicted, or hidden by the focus filter)."""
    below = 0
    for entry_seq, row_count, _ in reversed(entries):
        if entry_seq == seq:
            return below + row_count - 1, below
        below += row_count
    return None


def center_view_offset(top_offset, log_h, max_offset):
    """view_offset that puts the row at `top_offset` on the middle screen row of a
    `log_h`-tall body, clamped to the scrollable range."""
    log_h = max(1, log_h)
    rows_below_center = log_h - 1 - log_h // 2
    return max(0, min(max_offset, top_offset - rows_below_center))


def initial_match_seq(matches, entries, view_offset):
    """Where a fresh `\\find` lands: the newest match at or above the bottom of the current
    view (logs are read bottom-up), else the newest match overall. None if no matches."""
    if not matches:
        return None
    match_set = set(matches)
    below = 0
    for seq, row_count, _ in reversed(entries):
        if seq in match_set and below + row_count - 1 >= view_offset:
            return seq
        below += row_count
    return matches[-1]


def step_match_seq(matches, current, direction):
    """Next match from `current` toward 'older' (Tab) or 'newer' (Shift+Tab), wrapping at
    either end. `current` needn't still be a match (e.g. evicted) — steps from where it was."""
    if not matches:
        return None
    if current is None:
        return matches[-1] if direction == 'older' else matches[0]
    if direction == 'older':
        i = bisect.bisect_left(matches, current) - 1
        return matches[i] if i >= 0 else matches[-1]
    i = bisect.bisect_right(matches, current)
    return matches[i] if i < len(matches) else matches[0]


def match_position(matches, current):
    """1-based position of `current` among `matches` (oldest = 1), or None if absent."""
    i = bisect.bisect_left(matches, current) if current is not None else len(matches)
    if i < len(matches) and matches[i] == current:
        return i + 1
    return None


def format_find_status(query, position, total):
    """Header indicator text, e.g. `find "timeout"  3/17` (`-/17` once the current match
    has been evicted or filtered out)."""
    pos = str(position) if position is not None else '-'
    return f'find "{query}"  {pos}/{total}'


def rows_meta(entries, view_offset, height):
    """(seq, row_in_line) for each row RingLog.visible_rows(view_offset, height) returns,
    in the same order — lets the renderer tell which line (and which wrapped piece of it)
    each drawn row belongs to."""
    height = max(0, height)
    view_offset = max(0, view_offset)
    need = view_offset + height
    collected_rev = []
    for seq, row_count, _ in reversed(entries):
        if len(collected_rev) >= need:
            break
        collected_rev.extend((seq, r) for r in reversed(range(row_count)))
    collected_rev.reverse()
    end = max(0, len(collected_rev) - view_offset)
    start = max(0, end - height)
    return collected_rev[start:end]


def row_highlight_spans(plain, query, row_in_line, width, row_len):
    """Inclusive (start_col, end_col) spans of `query` matches falling on one wrapped row.
    wrap_line() character-wraps, so row r of a line covers chars [r*width, r*width+row_len)
    — a match crossing a wrap boundary is split across both rows."""
    row_start = row_in_line * max(1, width)
    row_end = row_start + row_len
    spans = []
    for start, end in match_spans(plain, query):
        lo = max(start, row_start)
        hi = min(end, row_end)
        if lo < hi:
            spans.append((lo - row_start, hi - 1 - row_start))
    return spans
