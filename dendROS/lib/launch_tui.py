"""Full-screen TUI render path for `ros2 launch` (launch_mode: tui).

Curses-owning layer — manual-testing only, same accepted gap as dendros_config.py's own
curses interaction. Pure/testable logic (ANSI parsing, wrapping, selection math, escape-
sequence decoding) lives in lib/tui_pure.py (clipboard helpers in lib/tui_clipboard.py); drawing methods live in
lib/launch_tui_render.py's `_TuiRenderMixin`; console command handling (the backslash-key
command bar, `focus`/`clear`, cross-process command mailbox) lives in lib/launch_tui_console.py's
`_TuiConsoleMixin` and lib/console_commands.py; this module owns session state/event handling
and drives it all from real screen/keyboard/mouse events.

Run-wide lifecycle (the reader thread, the RingLog, disable/enable, Ctrl-C outside a
session, falling back to classic output) lives in lib/launch_tui_run.py's run_tui(), which
calls curses.wrapper(_tui_main) once per session. This module owns one session: the main
thread drains the reader's queue on a 50ms tick and owns curses exclusively; _tui_main
returns 'disabled' when `dendros disable` fires mid-run.

Ctrl-C: SIGINT only reaches the main thread, so _TuiSession.run()'s getch() loop catches
KeyboardInterrupt itself and calls ca_module.enter_shutdown_mode() directly (a second one
quits the viewer); run_tui() handles the ones that land anywhere else.

Rendering: RingLog (lib/tui_ringlog.py) is the sole scrollback source of truth — nothing is
projected onto a persistent pad; each redraw rewraps on demand for the current viewport. A
redraw is skipped when nothing visible changed, since some terminals clear an active mouse
selection on *any* child-process output, not just visible changes — the scrollbar is drawn
separately so it can still update on that same skip path.

Mouse selection is always on (no mode key): DendROS renders its own highlight
(sel_anchor/sel_cursor) rather than relying on terminal-native selection, which any repaint
would destroy. Enabled via raw DECSET sequences (1002+1006, SGR extended coordinates) rather
than curses.mousemask()/getmouse() (legacy X10 protocol, corrupts past column ~223), parsed
by hand off scr.getch()'s raw bytes. Requires scr.keypad(False): with the curses default,
ncurses matches the SGR prefix against its own mouse handling and emits a premature
KEY_MOUSE without buffering the rest of the report — so nav keys are hand-decoded too rather
than left to curses' terminfo translation.

Clipboard: on release, a drag copies via both OSC 52 (not universally honored) and a local
xclip/xsel/wl-copy tool if present. Neither confirms success, so the "Copied" toast fires on
any attempt.
"""

import os
import queue
import threading
import time

from lib import __version__
from lib.colors import DENDROS_TAG
from lib.console_commands import node_identity_names
from lib.console_spec import Completer
from lib.global_config import is_disable_flag_set
from lib.launch_tui_console import _TuiConsoleMixin, _TOAST_DIM_UNTIL
from lib.launch_tui_find import _TuiFindMixin
from lib.launch_tui_help import _TuiHelpMixin
from lib.launch_tui_input import _TuiInputMixin, read_escape_sequence
from lib.launch_tui_render import _TuiRenderMixin
from lib.tui_pure import (
    quantize_rgb_to_256,
    segments_from_ansi,
    PairCache,
)
from lib.tui_clipboard import find_clipboard_tool

# True black: terminfo can't read back the terminal's real background, and most dark themes
# use a grey close enough that a computed offset wouldn't contrast reliably.
_HEADER_BG_RGB = (0, 0, 0)


# ── Curses-owning layer (manual-testing only) ──────────────────────────────────

def _tui_main(scr, ring, session, stop_event, ca_module):
    import curses

    curses.curs_set(0)
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    scr.timeout(50)
    # keypad(False) deliberately: with keypad(True) ncurses matches the SGR mouse prefix
    # against its own handling and emits a premature KEY_MOUSE without buffering the rest
    # of the report (confirmed via pty testing) — see module docstring.
    scr.keypad(False)

    # Raw DECSET mouse-tracking enable (see module docstring). Bracketed in try/finally so
    # the disable sequence fires on every exit path, since curses.wrapper() doesn't know
    # about a mode it never enabled. flushinp() discards stray bytes from before this
    # session (matters on re-open after a disable gap too).
    try:
        os.write(1, b'\x1b[?1002h\x1b[?1006h')
        curses.flushinp()
    except OSError:
        pass
    try:
        session_obj = _TuiSession(scr, ring, session, stop_event, ca_module, curses)
        session['opened'] = True
        try:
            return session_obj.run()
        finally:
            session['banner_text'] = session_obj.banner_text  # persisted by run_tui()
    finally:
        # Also covers _TuiSession.__init__ raising after it installed its sink.
        ca_module.set_sink(None)
        try:
            os.write(1, b'\x1b[?1006l\x1b[?1002l')
        except OSError:
            pass


class _TuiSession(_TuiRenderMixin, _TuiConsoleMixin, _TuiFindMixin, _TuiHelpMixin, _TuiInputMixin):
    """One curses.wrapper() session's worth of state and event handling. Drawing methods
    (_draw_segments/_draw_banner/_draw_scrollbar/_redraw/_draw_console) come from
    _TuiRenderMixin in lib/launch_tui_render.py; console command handling (_cmd_focus/
    _cmd_clear/_apply_console_command/_check_remote_command/...) comes from
    _TuiConsoleMixin in lib/launch_tui_console.py; `\\find` search (_cmd_find/_find_step/...)
    comes from _TuiFindMixin in lib/launch_tui_find.py; the `\\help` overlay comes from
    _TuiHelpMixin in lib/launch_tui_help.py; mouse/nav input handling
    (_screen_to_content/_handle_mouse/_handle_nav) comes from _TuiInputMixin in
    lib/launch_tui_input.py — all three split out purely to keep this file's core
    session/event-loop logic and the other concerns separately sized, not because any of
    them is reusable alone.
    """

    def __init__(self, scr, ring, session, stop_event, ca_module, curses):
        self.scr = scr
        self.ring = ring
        self.session = session
        self.lock = session.setdefault('lock', threading.Lock())
        self.stop_event = stop_event
        self.ca_module = ca_module
        self.curses = curses

        self.pair_cache = PairCache(curses)
        self.header_bg = quantize_rgb_to_256(*_HEADER_BG_RGB)
        self.banner_h = 1  # colored [dendROS] tag + version; crash/param alerts render right of it
        self.header_segments = segments_from_ansi(DENDROS_TAG)
        self.version_text = f' v{__version__} '

        # Adopt the queue run_tui() pre-created (holds any lines from before curses was up);
        # a session reopened after a disable gap gets a fresh one.
        with self.lock:
            self.q = session['q'] if session.get('q') is not None else queue.Queue()
            session['q'] = self.q
            session['mode'] = 'tui'
        # Review mode (`dendros reopen`, lib/launch_tui_review.py): read-only replay of a saved run.
        self.review = session.get('review', False)
        self.review_label = session.get('review_label', '')
        self.banner_text = session.get('banner_text', '') if self.review else ''
        self.copy_toast_at = None  # monotonic() timestamp of the last copy, or None

        ca_module.set_sink(lambda text: self.q.put(('banner', text)))
        if ca_module._dead_nodes:
            ca_module.print_alert_banner()  # reopening with a node already dead — surface now

        self.view_offset = 0  # 0 = following the live tail; >0 = scrolled back N rows (pinned)
        self.last_tail_growth = ring.tail_growth()  # as of the last _sync_pin(), for the pin
        self.eof = stop_event.is_set()
        self.last_disable_check = 0.0

        # Mouse-driven selection: sel_anchor (press point) / sel_cursor (drag/release point),
        # both None or (offset, col), tail-relative like view_offset. Always on, no mode toggle.
        self.sel_anchor = None
        self.sel_cursor = None
        self.mouse_down = False  # True between a left-button press and its matching release
        self.clipboard_tool_missing = find_clipboard_tool() is None  # checked once per session

        # `\`-console: see lib/launch_tui_console.py's _TuiConsoleMixin for command handling.
        self.console_active = False       # True while capturing local keystrokes
        self.console_buffer = ''
        self.console_error = None         # last error message text, or None
        self.console_error_at = None      # monotonic() timestamp, mirrors copy_toast_at's fade
        self.filter_node = None           # currently focused node name, or None (unfiltered)
        self.grep_query = None            # active `grep` text, or None (see _apply_filters())
        self.min_level = None             # active `level` ('warn', ...), or None
        # `mute`d node names. Lives in the run-wide `session` dict (mutated in place), not
        # per _TuiSession: it must survive a disable/enable reopen, and run_tui() saves it
        # with the run for `dendros reopen` (lib/tui_history.py).
        self.muted_nodes = session.setdefault('muted', set())
        self.mode_stack = []              # active 'focus'/'level'/'grep'/'find', oldest-first; Esc pops the last
        self.known_nodes = self._build_known_nodes_from_ring()
        self.last_command_check = 0.0     # 1x/sec poll gate for the remote command mailbox
        self._init_console_colors()       # sets self.console_fg/console_bg
        self._init_find_state()           # `\find`: see lib/launch_tui_find.py
        self._init_help_state()           # `\help` overlay: see lib/launch_tui_help.py
        self.completer = Completer()      # console-bar Tab completion (lib/console_spec.py)
        # The ring outlives this session (disable/enable reopen): re-sync its filter with
        # this session's state — only mutes carry over, focus/grep/level/find start fresh.
        self._apply_filters()

    def _disabled_system_wide(self):
        if self.review:
            return False
        now = time.monotonic()
        if now - self.last_disable_check < 1.0:
            return False
        self.last_disable_check = now
        return is_disable_flag_set()

    def _drain_queue(self):
        drained = False
        while True:
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                break
            drained = True
            if kind == 'line':
                colored, node_name, logger_name = payload
                # Strip \r/\n: curses' addstr() treats an embedded newline as a real
                # cursor action, producing a spurious blank row otherwise.
                segments = segments_from_ansi(colored.rstrip('\r\n'))
                plain = ''.join(seg[0] for seg in segments)
                self.ring.append(segments, plain, node_name, logger_name)
                self.known_nodes |= node_identity_names(node_name, logger_name)
            elif kind == 'banner':
                self.banner_text = payload
            elif kind == 'eof':
                self.eof = True
        return drained

    def _sync_pin(self, log_h):
        # Keeps a scrolled-back view_offset (or an active/just-finished selection) pointed
        # at the same absolute content as the tail grows, instead of silently drifting.
        # Shifts by the rows appended at the tail (ring.tail_growth()), not by the change in
        # total_rows(): once the scrollback is full every append also evicts a line at the
        # head, which leaves total_rows() flat while the content under a fixed tail offset
        # still moves. Rewraps and filter changes re-baseline separately (_rewrap_keeping_view(),
        # _reset_view_after_filter_change()). Idempotent with no intervening appends.
        growth = self.ring.tail_growth()
        delta = growth - self.last_tail_growth
        if delta and (self.sel_anchor is not None or self.view_offset > 0 or self.find_pinned):
            self.view_offset += delta
            if self.sel_anchor is not None:
                self.sel_anchor = (self.sel_anchor[0] + delta, self.sel_anchor[1])
            if self.sel_cursor is not None:
                self.sel_cursor = (self.sel_cursor[0] + delta, self.sel_cursor[1])
        self.last_tail_growth = growth
        max_offset = max(0, self.ring.total_rows() - log_h)
        self.view_offset = max(0, min(self.view_offset, max_offset))
        return max_offset

    def run(self):
        curses = self.curses
        scr = self.scr
        needs_redraw = True  # always draw once before the first getch()
        prev_banner_text = self.banner_text
        prev_eof = self.eof
        prev_copy_toast_active = False
        prev_console_visible = False
        prev_find_status = None
        try:
            while True:
                if self._disabled_system_wide():
                    # `dendros disable` from elsewhere — tear down, hand off to
                    # passthrough, let run_tui() decide whether to wait for a re-enable.
                    # Under the lock: everything already queued lands in RingLog, and the
                    # reader's next line sees 'passthrough' — nothing falls in between.
                    with self.lock:
                        self._drain_queue()
                        self.session['q'] = None
                        self.session['mode'] = 'passthrough'
                    return 'disabled'

                if self._check_remote_command():
                    # `dendros focus`/`dendros clear` from elsewhere — nothing else marks
                    # this tick dirty when a filter changes with no accompanying keypress.
                    needs_redraw = True

                drained = self._drain_queue()
                # Redraw only when something visible changed. While scrolled back, new
                # tail lines land outside the pinned viewport and must NOT trigger one —
                # most terminals clear an active selection on *any* child-process output,
                # so not calling doupdate() at all is what actually protects it.
                # The find indicator's counter moves as matching lines stream in (or get
                # evicted), even while the body itself is frozen on the current match.
                find_status = self._find_status()
                header_changed = (self.banner_text != prev_banner_text or self.eof != prev_eof
                                  or find_status != prev_find_status)
                # The toast fades on a wall-clock timer independent of any key/output
                # activity, so it needs its own redraw trigger; safe regardless of the pin
                # since it repaints identical content with only the header corner changing.
                copy_toast_active = False
                if self.copy_toast_at is not None:
                    if time.monotonic() - self.copy_toast_at < _TOAST_DIM_UNTIL:
                        copy_toast_active = True
                    else:
                        self.copy_toast_at = None  # expired; this tick's redraw erases it
                toast_changed = copy_toast_active != prev_copy_toast_active
                # Same wall-clock-fade treatment for the console error toast, which can be
                # set by a remote command even while the local console bar is closed.
                console_error_active = False
                if self.console_error is not None:
                    if time.monotonic() - self.console_error_at < _TOAST_DIM_UNTIL:
                        console_error_active = True
                    else:
                        self.console_error = None
                        self.console_error_at = None
                console_visible = self.console_active or console_error_active
                console_visible_changed = console_visible != prev_console_visible
                # An active selection always counts as "not following the tail", even at
                # view_offset 0, so new output can't repaint it away mid-drag.
                # Same for a find frozen on its match (find_pinned).
                viewport_follows_tail = (self.sel_anchor is None and self.view_offset == 0
                                         and not self.find_pinned)
                if (needs_redraw or header_changed or copy_toast_active or toast_changed
                        or console_error_active or console_visible_changed
                        or (drained and viewport_follows_tail)):
                    self._redraw()
                    prev_banner_text = self.banner_text
                    prev_eof = self.eof
                    prev_copy_toast_active = copy_toast_active
                    prev_console_visible = console_visible
                    prev_find_status = find_status
                    needs_redraw = False
                elif drained:
                    # Body redraw was skipped for the pin, but the scrollbar has nothing
                    # of its own to protect, so keep it live independently.
                    self._draw_scrollbar()
                    scr.noutrefresh()
                    curses.doupdate()

                try:
                    ch = scr.getch()
                except KeyboardInterrupt:
                    if self.session.get('interrupted'):
                        break  # second Ctrl-C: quit the viewer
                    self.session['interrupted'] = True
                    self.ca_module.enter_shutdown_mode()
                    continue

                if ch == -1:
                    continue  # timeout, no key — stay open even after eof so scrollback stays usable

                needs_redraw = True

                if ch == curses.KEY_RESIZE:
                    scr.clear()  # wipe stale content; next _redraw() recomputes from getmaxyx()
                elif self.help_open:
                    self._help_key(ch)  # the overlay captures every key while it's up
                elif self.console_active:
                    self._console_key(ch)
                elif ch == ord('\\'):
                    self.console_active = True
                    self.console_buffer = ''
                    self.console_error = None
                    self.completer.reset()
                elif ch == 27:
                    # keypad(False): every arrow key/nav key/mouse report arrives raw here.
                    result = read_escape_sequence(scr, curses)
                    if result is None:
                        pass
                    elif result[0] == 'escape':
                        self._escape_mode()  # bare Esc: exit the most recent focus/level/grep/find
                    elif result[0] == 'nav':
                        self._handle_nav(result[1])
                    else:  # result[0] == 'mouse'
                        self._handle_mouse(result[1])
                elif ch == 9:  # Tab: next (older) find match; Shift+Tab arrives as nav 'backtab'
                    self._find_step('older')
                elif ch == ord('q') and self.eof:
                    # Only quit once the process has exited — Ctrl-C is how you stop it early.
                    break
        finally:
            try:
                self.ca_module.set_sink(None)
            except Exception:
                pass
        return None
