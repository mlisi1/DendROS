"""`dendros reopen`'s read-only TUI over a saved run (lib/tui_history.py).

Split out of lib/launch_tui.py to keep that file under the ~500-line threshold. Reuses
_tui_main/_TuiSession unchanged except for the session dict's `review` keys, which
_TuiSession reads to skip live-only behavior (cross-process disable/command polling) and to
show the review label in the header. Curses-owning — manual-testing only.
"""

import locale
import queue
import threading
import time

from lib.launch_tui import _tui_main
from lib.tui_pure import RingLog


class _NullCrashAlert:
    """Stand-in for lib.crash_alert in review_tui(): a saved run has no live deaths to
    track — its final crash banner (if any) is restored as static header text instead."""
    _dead_nodes = {}

    @staticmethod
    def set_sink(fn):
        pass

    @staticmethod
    def print_alert_banner():
        pass

    @staticmethod
    def enter_shutdown_mode():
        pass


def review_tui(last_run):
    """Entry point for `dendros reopen` (dendros_reopen.py): reopen a saved run
    (lib/tui_history.load_last_run()'s dict) in a read-only TUI. Same _TuiSession as a live
    run — scrolling, selection/copy, focus/find/clear all work — with the process already
    finished and no polling of the cross-process disable flag or command mailbox (those
    belong to live launches; a review must never steal a `dendros focus` meant for one)."""
    import curses
    locale.setlocale(locale.LC_ALL, '')

    entries = last_run['entries']
    ring = RingLog(maxlen=max(1, len(entries)))
    for segments, plain, node_name, logger_name in entries:
        ring.append(segments, plain, node_name, logger_name)

    stop_event = threading.Event()
    stop_event.set()  # process already finished: `q` quits right away
    session = {
        'q': queue.Queue(),
        'review': True,
        'review_label': _review_label(last_run),
        'banner_text': last_run.get('banner', ''),
    }
    curses.wrapper(_tui_main, ring, session, threading.Event(), stop_event, _NullCrashAlert)


def _review_label(last_run):
    argv = list(last_run.get('argv') or [])
    if argv and argv[0] == 'launch':
        argv = argv[1:]
    when = ''
    if last_run.get('saved_at'):
        when = time.strftime('%H:%M', time.localtime(last_run['saved_at']))
    parts = [p for p in (' '.join(argv), when and f'ended {when}') if p]
    return 'last run' + (': ' + ', '.join(parts) if parts else '')
