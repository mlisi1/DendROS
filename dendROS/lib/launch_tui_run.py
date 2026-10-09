"""TUI launch mode's run-wide lifecycle: run_tui(), the entry point from
dendROS_pipe.py::main() when launch_mode is 'tui'. Split out of lib/launch_tui.py (which
keeps one curses session's worth of state — _tui_main/_TuiSession) to keep files sized.

run_tui() owns everything that outlives a single curses session: the RingLog, the one
background reader thread consuming the launch output, and the mode that thread routes each
line by — 'tui' (queued for the current _TuiSession), 'passthrough' (`dendros disable`:
printed raw, still recorded) or 'classic' (curses failed: printed colorized). Every switch
between them happens under one lock, so no line is lost or routed twice; the reader stays
the generator's only consumer for the whole run, whatever happens to curses. Ctrl-C outside
a session's getch() (mid-redraw, while disabled) is caught here too and treated like the
one inside it: shutdown mode, keep showing output until the launch has exited.
Curses-owning — manual-testing only.
"""

import locale
import queue
import sys
import threading
import time

from lib.config_loader import resolve_node
from lib.global_config import is_disable_flag_set, pop_tui_command
from lib.launch_tui import _tui_main
from lib.tui_history import save_last_run
from lib.tui_pure import segments_from_ansi
from lib.tui_ringlog import RingLog


def run_tui(stdin_lines, colorize_fn, ca_module, pw_module, param_alert, param_alert_style,
            color_map, tag_map, style_map, tag_style, show_tag, global_cfg, launch_argv=None):
    """Entry point from dendROS_pipe.py::main() when launch_mode is 'tui'. The reader
    thread and RingLog persist across a mid-run disable/enable cycle (see module docstring).
    Returns once the run is over: a normal quit, or the process ending while disabled.
    On the way out the scrollback is saved as this terminal's last run, for
    `dendros reopen` (lib/tui_history.py, lib/launch_tui_review.py)."""
    import curses
    locale.setlocale(locale.LC_ALL, '')  # required for curses to render multi-byte UTF-8

    try:
        scrollback = int(global_cfg.get('tui_scrollback_lines', 5000))
    except (TypeError, ValueError):
        scrollback = 5000
    scrollback = max(1, scrollback)

    ring = RingLog(maxlen=scrollback)
    stop_event = threading.Event()  # set once = stdin_lines is exhausted, for good
    # Run-wide state shared with the reader thread and each _TuiSession:
    #   mode  — 'tui' (queue lines for curses), 'passthrough' (disabled: print raw) or
    #           'classic' (curses failed: print colorized, like the classic loop)
    #   q     — the current session's queue.Queue(), or None outside a session. Created up
    #           front (and adopted by the first _TuiSession) so lines the reader produces
    #           before curses finishes starting are buffered rather than dropped.
    #   lock  — held by the reader for each whole line, and by the main thread for every
    #           mode/queue switch, so a line is never routed by a half-switched state (e.g.
    #           seen as 'tui' but put on a queue the main thread just abandoned).
    session = {'q': queue.Queue(), 'mode': 'tui', 'lock': threading.Lock()}
    disable_check = {'at': 0.0, 'set': False}  # classic-fallback mode's 1x/sec flag poll

    def _record(text, node_name, logger_name):
        # Lines printed outside curses still go into RingLog — parsed, with node identity —
        # so a re-enabled session (or `dendros reopen`) shows them like any other line,
        # filterable by focus/mute, instead of as raw escape sequences.
        segments = segments_from_ansi(text.rstrip('\r\n'))
        ring.append(segments, ''.join(seg[0] for seg in segments), node_name, logger_name)

    def _handle_line(line):
        mode = session['mode']
        if mode == 'passthrough':
            sys.stdout.write(line)
            sys.stdout.flush()
            try:
                _record(*colorize_fn(line))  # displayed raw now, colorized when re-enabled
            except Exception:
                pass
            return
        if mode == 'classic':
            now = time.monotonic()
            if now - disable_check['at'] >= 1.0:
                disable_check['at'] = now
                disable_check['set'] = is_disable_flag_set()
            if disable_check['set']:
                sys.stdout.write(line)
                sys.stdout.flush()
                return
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
                    if mode == 'tui':
                        ca_module.print_alert_banner()  # refresh/clear the pinned banner
        colored, node_name, logger_name = colorize_fn(line)
        notifs = []
        if param_alert:
            # Param-change notifications aren't tied to a specific line's node identity
            # (see lib/launch_tui_console.py's known-nodes tracking).
            notifs = list(pw_module.drain(color_map, tag_map, style_map, tag_style,
                                          show_tag, param_alert_style))
        if mode == 'tui':
            q = session['q']
            q.put(('line', (colored, node_name, logger_name)))
            for notif in notifs:
                q.put(('line', (notif, None, None)))
        else:  # 'classic'
            sys.stdout.write(colored)
            _record(colored, node_name, logger_name)
            for notif in notifs:  # already newline-terminated
                sys.stdout.write(notif)
                _record(notif, None, None)
            sys.stdout.flush()

    def _reader():
        try:
            for line in stdin_lines:
                with session['lock']:
                    _handle_line(line)
        except Exception:
            pass
        finally:
            with session['lock']:
                if session['mode'] == 'tui' and session['q'] is not None:
                    session['q'].put(('eof', None))
            stop_event.set()

    def _wait_for_launch_end():
        # Outside curses (disabled, or curses unusable): the reader keeps printing; just
        # outlive the launch. Ctrl-C here is the user stopping the launch — note it so the
        # resulting deaths aren't reported as crashes, and keep waiting for the output.
        while not stop_event.is_set():
            try:
                stop_event.wait(0.5)
            except KeyboardInterrupt:
                ca_module.enter_shutdown_mode()
                session['interrupted'] = True

    def _fall_back_to_classic():
        # curses failed mid-run (it couldn't start, or crashed). The reader thread is
        # still the only consumer of stdin_lines — main() must not loop over the same
        # generator — so switch the reader itself to classic-style output and print what
        # the abandoned session had queued but not drawn yet.
        ca_module.set_sink(None)
        with session['lock']:
            q = session['q']
            session['q'] = None
            session['mode'] = 'classic'
            while q is not None:
                try:
                    kind, payload = q.get_nowait()
                except queue.Empty:
                    break
                if kind == 'line':
                    sys.stdout.write(payload[0].rstrip('\r\n') + '\n')
            sys.stdout.flush()
        _wait_for_launch_end()

    # A `dendros focus/find/…` sent while no TUI was running is stale by now — it was
    # meant for some earlier launch, not this one.
    pop_tui_command()

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        while True:
            try:
                result = curses.wrapper(_tui_main, ring, session, stop_event, ca_module)
            except KeyboardInterrupt:
                # Ctrl-C landed outside getch() (mid-redraw, mid-drain): same meaning as
                # inside it — the launch is stopping. Reopen; RingLog replays everything.
                ca_module.enter_shutdown_mode()
                session['interrupted'] = True
                continue
            except Exception:
                _fall_back_to_classic()
                return
            if result != 'disabled':
                return  # normal quit — fully done

            # Disabled mid-run: wait for a re-enable, or give up once the process has exited.
            while not stop_event.is_set() and is_disable_flag_set():
                try:
                    time.sleep(0.5)
                except KeyboardInterrupt:
                    ca_module.enter_shutdown_mode()
                    session['interrupted'] = True
            if stop_event.is_set():
                return
            # else: flag cleared while still running — loop back and reopen curses
    finally:
        ca_module.set_sink(None)
        if session.get('opened'):  # never saved when the TUI didn't actually come up
            try:
                save_last_run(ring.entries(), launch_argv, session.get('banner_text', ''),
                              muted=session.get('muted', ()))
            except Exception:
                pass
