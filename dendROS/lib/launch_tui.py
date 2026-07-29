"""Full-screen TUI render path for `ros2 launch` (launch_mode: tui).

Architecture
------------
Pure layer (importable and unit-testable without a real curses/tty):
  - quantize_rgb_to_256 / segments_from_ansi : ANSI SGR -> (text, fg256, bg256, bold) runs.
  - PairCache   : lazily allocates/reuses curses color-pair slots, LRU-evicted when exhausted.
  - RingLog     : bounded scrollback (collections.deque) that also projects each appended line
                  onto a curses pad (or a fake pad double, for tests) via a single append() call,
                  keeping pad content and a parallel plain-text index 1:1 aligned (ready for a
                  future `/` search without a data-model change).

Curses-owning layer (manual-testing only — same accepted gap as dendros_config.py's own curses
interaction, which is likewise untested by the unit suite):
  - run_tui/_tui_main : curses.wrapper entry point. A background daemon thread consumes the same
    _iter_stdin() generator the classic loop uses and does the existing per-line work (crash-alert
    detection, colorize, param-watcher drain), pushing only tagged data onto a queue.Queue() — it
    never touches curses objects. The main thread drains the queue on a 50ms tick, appends to
    RingLog, redraws a pinned banner row (crash/param alerts, via ca.set_sink()) and the scrollback
    pad, and handles keyboard navigation (PageUp/PageDown/Home/End, q/Ctrl-C to quit).

Ctrl-C handling is intentionally different from the classic loop: SIGINT is only ever delivered to
the main thread, so the background reader thread's blocking read() never sees it and _iter_stdin()'s
own first-interrupt handling never fires there. The main thread's getch() loop catches
KeyboardInterrupt itself and calls ca_module.enter_shutdown_mode() directly instead.
"""

import collections
import queue
import re
import threading

from lib.config_loader import resolve_node

_SGR_RE = re.compile(r'\033\[([0-9;]*)m')


def quantize_rgb_to_256(r, g, b):
    """Map a 24-bit RGB triple to the nearest xterm-256 color-cube index (16-231).

    curses can't portably render real truecolor without hijacking the terminal's global
    palette, so TUI mode accepts a 256-color approximation; classic mode stays exact since
    it writes raw ANSI straight through.
    """
    def _to_cube(v):
        return round(max(0, min(255, v)) / 255 * 5)
    r6, g6, b6 = _to_cube(r), _to_cube(g), _to_cube(b)
    return 16 + 36 * r6 + 6 * g6 + b6


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
    for m in _SGR_RE.finditer(line):
        text = line[pos:m.start()]
        if text:
            segments.append((text, fg, bg, bold))
        for n, kind, val in _parse_sgr_params(m.group(1)):
            if n == 0:
                fg = bg = None
                bold = False
            elif n == 1:
                bold = True
            elif n == 22:
                bold = False
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
        pos = m.end()
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
    """

    def __init__(self, maxlen, pad=None, pair_cache=None):
        self.maxlen = maxlen
        self._lines = collections.deque(maxlen=maxlen)
        self._pad = pad
        self._pair_cache = pair_cache

    def __len__(self):
        return len(self._lines)

    def __getitem__(self, idx):
        return self._lines[idx]

    def plain_lines(self):
        return [plain for _, plain in self._lines]

    def append(self, segments, plain_text):
        self._lines.append((segments, plain_text))
        if self._pad is not None:
            self._render_last(segments)

    def _render_last(self, segments):
        pad = self._pad
        try:
            max_y, max_x = pad.getmaxyx()
        except Exception:
            return
        pad.scroll(1)
        row = max(0, max_y - 1)
        try:
            pad.move(row, 0)
            pad.clrtoeol()
        except Exception:
            pass
        col = 0
        for text, fg, bg, bold in segments:
            if col >= max_x:
                break
            attr = 0
            if self._pair_cache is not None and (fg is not None or bg is not None or bold):
                attr = self._pair_cache.attr_for(fg, bg, bold)
            try:
                pad.addstr(row, col, text[:max(0, max_x - col)], attr)
            except Exception:
                pass
            col += len(text)


# ── Curses-owning layer (manual-testing only) ──────────────────────────────────

def run_tui(stdin_lines, colorize_fn, ca_module, pw_module, param_alert, param_alert_style,
            color_map, tag_map, style_map, tag_style, show_tag, global_cfg):
    """Entry point called from dendROS_pipe.py::main() when launch_mode is 'tui'."""
    import curses
    curses.wrapper(
        _tui_main, stdin_lines, colorize_fn, ca_module, pw_module,
        param_alert, param_alert_style, color_map, tag_map, style_map, tag_style, show_tag,
        global_cfg,
    )


def _tui_main(scr, stdin_lines, colorize_fn, ca_module, pw_module, param_alert, param_alert_style,
              color_map, tag_map, style_map, tag_style, show_tag, global_cfg):
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
    try:
        scrollback = int(global_cfg.get('tui_scrollback_lines', 5000))
    except (TypeError, ValueError):
        scrollback = 5000
    scrollback = max(1, scrollback)

    max_y, max_x = scr.getmaxyx()
    banner_h = 1
    pad = curses.newpad(scrollback, max(1, max_x))
    pad.scrollok(True)
    pad.idlok(True)
    ring = RingLog(maxlen=scrollback, pad=pad, pair_cache=pair_cache)

    q = queue.Queue()
    banner_state = {'text': ''}

    ca_module.set_sink(lambda text: q.put(('banner', text)))

    def _reader():
        try:
            for line in stdin_lines:
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
                q.put(('line', colorize_fn(line)))
                if param_alert:
                    for notif in pw_module.drain(color_map, tag_map, style_map, tag_style,
                                                  show_tag, param_alert_style):
                        q.put(('line', notif))
        except Exception:
            pass
        finally:
            q.put(('eof', None))

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    view_offset = 0  # 0 = following the live tail; >0 = scrolled back N rows
    eof = False
    interrupted = False

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
                segments = segments_from_ansi(payload)
                plain = ''.join(seg[0] for seg in segments)
                ring.append(segments, plain)
            elif kind == 'banner':
                banner_state['text'] = payload
            elif kind == 'eof':
                eof = True
        return drained

    def _draw_banner(width):
        scr.move(0, 0)
        scr.clrtoeol()
        text = banner_state['text']
        if not text:
            if eof:
                hint = '-- process finished -- q: quit  PageUp/PageDown: scroll --'
                try:
                    scr.addstr(0, 0, hint[:width], curses.A_DIM)
                except curses.error:
                    pass
            return
        col = 0
        for seg_text, fg, bg, bold in segments_from_ansi(text):
            if col >= width:
                break
            attr = pair_cache.attr_for(fg, bg, bold) if (fg is not None or bg is not None or bold) else 0
            try:
                scr.addstr(0, col, seg_text[:max(0, width - col)], attr)
            except curses.error:
                pass
            col += len(seg_text)

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
            elif ch == ord('q'):
                break
    finally:
        try:
            ca_module.set_sink(None)
        except Exception:
            pass
