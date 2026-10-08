"""Clipboard helpers for the TUI launch mode's mouse selection (see lib/launch_tui_input.py).

Pure/testable (test/unit/test_launch_tui.py). Split out of lib/tui_pure.py to keep that module
under the project's ~500-line split threshold — this group is self-contained (no shared state
with the ANSI/wrap/RingLog code there).
"""

import base64
import shutil
import subprocess


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
