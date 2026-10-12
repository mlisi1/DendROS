"""Per-terminal persistence of the TUI launch mode's last run, behind `dendros reopen`.

When a `ros2 launch` TUI run ends, run_tui() (lib/launch_tui.py) saves the RingLog
scrollback here; `dendros reopen` (dendros_reopen.py) loads it back into a read-only TUI.
Only the last run per terminal is kept.

"Terminal" = the interactive shell that ran `ros2 launch`: dendROS.sh passes its `$$` as
DENDROS_SHELL_PID to both the launch pipe and `dendros reopen`, so each shell reopens its
own last run even with several terminals running launches side by side. Falls back to
os.getppid() (the invoking shell, for both entry points) when the variable is missing.

Format: JSONL — a header object ({version, saved_at, argv, banner, muted}), then one
[segments, plain_text, node_name, logger_name] array per RingLog entry. Entries are always
the full unfiltered scrollback — `mute` only hides lines, so the muted node names are stored
in the header and re-applied on reopen (a file without `muted` loads as nothing muted).
Pure/curses-free, unit-tested in test/unit/test_tui_history.py.
"""

import json
import os
import tempfile
import time

from lib.global_config import get_global_config_path

_FORMAT_VERSION = 1


def get_history_dir():
    """Directory holding one `<shell_pid>.jsonl` per terminal, next to defaults.yaml."""
    return os.path.join(os.path.dirname(get_global_config_path()), 'last_run')


def current_shell_id():
    value = os.environ.get('DENDROS_SHELL_PID', '').strip()
    if value.isdigit():
        return int(value)
    return os.getppid()


def get_history_path(shell_id=None):
    if shell_id is None:
        shell_id = current_shell_id()
    return os.path.join(get_history_dir(), f'{int(shell_id)}.jsonl')


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    except OSError:
        return False
    return True


def prune_stale(keep_id=None):
    """Delete saved runs whose shell no longer exists (closed terminals)."""
    hist_dir = get_history_dir()
    try:
        names = os.listdir(hist_dir)
    except OSError:
        return
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext != '.jsonl' or not stem.isdigit():
            continue
        pid = int(stem)
        if pid == keep_id or _pid_alive(pid):
            continue
        try:
            os.remove(os.path.join(hist_dir, name))
        except OSError:
            pass


def save_last_run(entries, argv=None, banner_text='', shell_id=None, muted=(), saved_at=None):
    """Atomically write `entries` ((segments, plain, node_name, logger_name) tuples, as
    RingLog stores them) as this terminal's last run, with the `muted` node names. Pass
    `saved_at` to keep the original end time when re-saving (a review's mute changes).
    Best-effort: never raises."""
    if shell_id is None:
        shell_id = current_shell_id()
    path = get_history_path(shell_id)
    hist_dir = os.path.dirname(path)
    try:
        os.makedirs(hist_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=hist_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                header = {
                    'version': _FORMAT_VERSION,
                    'saved_at': saved_at if saved_at is not None else time.time(),
                    'argv': list(argv or []),
                    'banner': banner_text or '',
                    'muted': sorted(muted or ()),
                }
                f.write(json.dumps(header) + '\n')
                for segments, plain, node_name, logger_name in entries:
                    f.write(json.dumps([[list(s) for s in segments], plain,
                                        node_name, logger_name]) + '\n')
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except Exception:
        return
    prune_stale(keep_id=shell_id)


def load_last_run(shell_id=None):
    """This terminal's last run as a dict {saved_at, argv, banner, muted, entries}, or None if
    nothing was saved (or the file is unreadable/from an incompatible version).
    `entries` come back in RingLog's tuple shape, segments included."""
    path = get_history_path(shell_id)
    try:
        with open(path, encoding='utf-8') as f:
            header = json.loads(f.readline())
            if not isinstance(header, dict) or header.get('version') != _FORMAT_VERSION:
                return None
            entries = []
            for raw in f:
                if not raw.strip():
                    continue
                segments, plain, node_name, logger_name = json.loads(raw)
                entries.append(([tuple(s) for s in segments], plain, node_name, logger_name))
    except (OSError, ValueError, TypeError):
        return None
    return {
        'saved_at': header.get('saved_at'),
        'argv': header.get('argv') or [],
        'banner': header.get('banner') or '',
        'muted': set(header.get('muted') or ()),
        'entries': entries,
    }
