"""Pure, curses-free helpers backing the TUI launch mode (see lib/launch_tui.py).

ANSI/SGR parsing, wrapping, RingLog scrollback, selection math, mouse/keyboard escape-sequence
decoding, clipboard encoding — no curses or thread dependency, so it's unit-tested directly
(test/unit/test_launch_tui.py). launch_tui.py's curses loop drives these from real events.
"""

import base64
import collections
import re
import shutil
import subprocess
import threading

# Matches any CSI sequence, not just SGR color codes, so non-color codes (e.g. '\033[K') are
# stripped instead of showing up as literal garbage text.
_CSI_RE = re.compile(r'\033\[([0-9;]*)([A-Za-z])')

# xterm's 256-color cube isn't evenly spaced (0, 95, 135, 175, 215, 255) — naive linear
# rounding picks badly wrong levels for dark colors.
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
    """Map a 24-bit RGB triple to the nearest xterm-256 index (color cube or grayscale ramp)."""
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))

    ri, rv = _nearest_cube_level(r)
    gi, gv = _nearest_cube_level(g)
    bi, bv = _nearest_cube_level(b)
    cube_idx = 16 + 36 * ri + 6 * gi + bi
    cube_dist = (r - rv) ** 2 + (g - gv) ** 2 + (b - bv) ** 2

    gray = round((r + g + b) / 3)  # 24-step grayscale ramp, indices 232-255
    gray_idx = max(0, min(23, round((gray - 8) / 10)))
    gray_val = 8 + gray_idx * 10
    gray_dist = (r - gray_val) ** 2 + (g - gray_val) ** 2 + (b - gray_val) ** 2

    if gray_dist < cube_dist:
        return 232 + gray_idx
    return cube_idx


def _parse_sgr_params(code_str):
    """Yield (n, kind, value): kind 'rgb'->(r,g,b) for 38;2/48;2, '256'->idx for 38;5/48;5,
    else 'code'->None for a plain numeric SGR code."""
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
            continue  # non-SGR CSI code, already stripped
        for n, kind, val in _parse_sgr_params(m.group(1)):
            if n == 0:
                fg = bg = None
                bold = False
            elif n == 1:
                bold = True
            elif n == 22:
                bold = False
            elif n == 7:
                # Reverse video: DendROS's inverted convention is bg + hollow black text
                # (matches param_watcher's _fg_to_bg), not curses' "default" foreground.
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
    """Character-wrap one line's colored segments into rows of at most `width` columns,
    splitting mid-segment so color survives a wrap boundary. Always returns >=1 row."""
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


# Selection positions are (offset, col): offset = row's distance from the tail (same units
# as RingLog.visible_rows()'s view_offset), col = character column within the row.

def _selection_bounds(anchor, cursor):
    """Order (anchor, cursor) into (lo_offset, lo_col, hi_offset, hi_col): hi = larger offset."""
    a_offset, a_col = anchor
    c_offset, c_col = cursor
    if a_offset > c_offset or (a_offset == c_offset and a_col > c_col):
        return c_offset, c_col, a_offset, a_col
    return a_offset, a_col, c_offset, c_col


def selection_span_for_row(row_tail_offset, row_len, anchor, cursor):
    """Inclusive (start_col, end_col) of `row_tail_offset` covered by the selection, or None."""
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
    """Join `rows` (RingLog.visible_rows() for exactly the anchor-to-cursor span, oldest
    first) into copyable text: continuation rows join with no separator, new logical lines
    get a real newline, first/last rows are trimmed to the selection's column bounds."""
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
    """Map a drawn body row (0-based) to its tail-relative offset, or None if out of range."""
    if body_row < 0 or body_row >= n_rows:
        return None
    return (n_rows - 1 - body_row) + view_offset


def compute_scrollbar_thumb(track_height, view_offset, max_offset, total_rows):
    """(thumb_start, thumb_height) in track-row units for a log-viewer scrollbar: thumb at
    the bottom when following the tail, top when fully scrolled back. (0, 0) if nothing to
    scroll."""
    track_height = max(0, track_height)
    if track_height == 0 or max_offset <= 0 or total_rows <= track_height:
        return 0, 0
    thumb_height = max(1, min(track_height, round(track_height * track_height / total_rows)))
    max_thumb_start = track_height - thumb_height
    frac = max(0.0, min(1.0, view_offset / max_offset))  # 0 = at tail, 1 = fully scrolled back
    thumb_start = max(0, min(max_thumb_start, round(max_thumb_start * (1 - frac))))
    return thumb_start, thumb_height


def decode_sgr_mouse(cb, cx, cy, terminator):
    """Decode an SGR mouse report into a dict. Cb: low 2 bits = button, bit 5 = motion, bit 6
    = wheel (low bit then means up/down instead of a button). Cx/Cy are 1-based on the wire;
    converted to 0-based to match curses."""
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


# Two CSI encodings for the same keys (ESC[A vs ESC[5~) -- xterm/VTE use both depending on
# the key. left/right decoded for completeness though nothing currently binds them.
_NAV_LETTER_ACTIONS = {'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left', 'H': 'home', 'F': 'end'}
_NAV_TILDE_ACTIONS = {'1': 'home', '7': 'home', '4': 'end', '8': 'end', '5': 'page_up', '6': 'page_down'}


def decode_navigation_key(final_byte, digits=''):
    """Decode a CSI nav sequence into an action string, or None. `final_byte` is '~' for the
    digit-prefixed tilde form (`digits` = accumulated digits), else the bare letter form."""
    if final_byte == '~':
        return _NAV_TILDE_ACTIONS.get(digits)
    if digits:
        return None
    return _NAV_LETTER_ACTIONS.get(final_byte)


_OSC52_MAX_BYTES = 1024 * 1024  # soft guard against a pathologically large selection


def build_osc52_sequence(text, max_bytes=_OSC52_MAX_BYTES):
    """Build the OSC 52 "set system clipboard" escape sequence. Not universally honored
    (confirmed absent on some VTE-based terminals) — see copy_via_system_clipboard_tool()."""
    data = text.encode('utf-8', errors='replace')[:max_bytes]
    b64 = base64.b64encode(data).decode('ascii')
    return f'\033]52;c;{b64}\a'.encode('ascii')


# Tried in order; first found on PATH wins. xclip/xsel need X11, wl-copy needs Wayland, so
# normally only one pair is ever installed.
_CLIPBOARD_COMMANDS = (
    ('xclip', '-selection', 'clipboard'),
    ('xsel', '--clipboard', '--input'),
    ('wl-copy',),
)


def find_clipboard_tool(which_fn=shutil.which):
    """First clipboard command from _CLIPBOARD_COMMANDS found on PATH, or None."""
    for cmd in _CLIPBOARD_COMMANDS:
        if which_fn(cmd[0]):
            return cmd
    return None


def copy_via_system_clipboard_tool(text, which_fn=shutil.which, run_fn=subprocess.run):
    """Best-effort copy via a local xclip/xsel/wl-copy, for terminals that don't honor OSC
    52 at all. Returns True if a tool ran (not proof it reached the clipboard), False if
    none was found. Errors are swallowed — this is always supplementary to the OSC 52 write."""
    cmd = find_clipboard_tool(which_fn)
    if cmd is None:
        return False
    try:
        run_fn(cmd, input=text.encode('utf-8', errors='replace'), timeout=2, check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return True


class PairCache:
    """Lazily allocates/reuses curses color-pair slots, LRU-evicted once COLOR_PAIRS is used up.
    `curses_module` is injectable for tests (a fake needs only init_pair/color_pair/COLOR_PAIRS/A_BOLD)."""

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
    """Bounded scrollback: (segments, plain_text) pairs. `_lines` is the sole source of
    truth — nothing is projected onto a persistent curses pad; visible_rows()/set_width()
    wrap on demand for whatever's actually visible, so a resize is just "wrap differently
    next redraw" with no replay step. append() runs from both the main thread (queue drain)
    and the reader thread (during a disable gap), so mutating methods take a lock.
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
        """Rewrap all retained history at a new width. No-op if unchanged — the only
        O(history) operation, and only runs once per actual resize."""
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
        """Up to `height` (segments, is_continuation) rows ending `view_offset` rows back
        from the tail. is_continuation marks a mid-line wrap (vs. a new logical line), so
        callers can rejoin text without spurious newlines. Also usable for an arbitrary
        historical range, not just the live viewport."""
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
