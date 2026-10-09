"""Command-handling methods for lib/launch_tui.py's `_TuiSession` (mixed in there as
`_TuiConsoleMixin`, alongside `_TuiRenderMixin` from lib/launch_tui_render.py).

Split out for the same reason `_TuiRenderMixin` was: a cohesive group of methods that still
depends on `_TuiSession`'s own state, pulled into its own file purely to keep file sizes
manageable (lib/launch_tui.py was already near the project's ~500-line split threshold before
this feature). Curses-owning like the rest of `_TuiSession` — manual-testing only; the pure
parsing/matching logic these methods call lives in lib/console_commands.py instead, where it's
unit-tested directly.

Extension point for future console commands: add a pure predicate/parser to
lib/console_commands.py if needed, a `_cmd_<name>` method here, and one entry in
`_COMMAND_HANDLERS` below. Neither the key dispatch in lib/launch_tui.py's run() nor
_apply_console_command()'s dispatch logic need to change per new command.
"""

import time

from lib.colors import _DENDROS_BLUE, _DENDROS_ORANGE
from lib.console_commands import (
    build_filter,
    canonical_node_name,
    drop_mode,
    format_filter_status,
    format_mute_status,
    node_identity_names,
    LEVEL_NAMES,
    parse_console_command,
    parse_level,
    push_mode,
)
from lib.global_config import pop_tui_command
from lib.launch_tui_input import read_escape_sequence

# Header toasts (console errors here, "Copied" in lib/launch_tui_render.py): bold -> normal
# -> dim -> gone, seconds since shown. One set of timings shared by both toasts.
_TOAST_BOLD_UNTIL = 1.2
_TOAST_NORMAL_UNTIL = 1.3
_TOAST_DIM_UNTIL = 1.4

# Palette slots for the console's brand colors (see _init_console_colors()). Chosen so that
# their *stock* xterm-256 colors already approximate the brand colors: some terminals
# (Konsole/Yakuake among them) accept curses' palette reprogramming without applying it,
# and with unrelated slots the console would then render in whatever those slots normally
# hold — the previous choice, 253/254 from the grey ramp, came out near-white on white.
#   24  = #005f87: a blue. (23 = #005f5f is numerically nearer to brand blue but reads teal.)
#   172 = #d78700: the nearest stock orange.
# Where reprogramming does apply, node colors that quantize to these two slots shift to the
# exact brand blue/orange for the session — at most a few RGB units, a cosmetic edge case.
_CONSOLE_BG_COLOR_SLOT = 24
_CONSOLE_FG_COLOR_SLOT = 172


def _rgb_to_curses_scale(rgb):
    # curses.init_color() takes each channel on a 0-1000 scale, not 0-255.
    return tuple(round(c * 1000 / 255) for c in rgb)


class _TuiConsoleMixin:

    # Command name -> handler method name. Adding a command is one pure helper (if needed,
    # in lib/console_commands.py) + one _cmd_* method below + one entry here.
    _COMMAND_HANDLERS = {
        'focus': '_cmd_focus',
        'grep': '_cmd_grep',
        'level': '_cmd_level',
        'mute': '_cmd_mute',
        'unmute': '_cmd_unmute',
        'clear': '_cmd_clear',
        'help': '_cmd_help',    # lives in lib/launch_tui_help.py's _TuiHelpMixin
        'find': '_cmd_find',    # lives in lib/launch_tui_find.py's _TuiFindMixin
    }

    def _build_known_nodes_from_ring(self):
        """Seed the lenient known-nodes set from whatever's already in the ring: every
        line's discovered node_name and logger_name (see console_commands.node_identity_names()
        and RingLog.node_identities()) — covers composable nodes (own logger_name, distinct
        from their container's node_name) and the rarer non-composable divergence alike.
        Re-derived (not just tracked incrementally) because run_tui() can reopen a fresh
        _TuiSession after a disable/re-enable cycle while `ring` itself persists across
        that boundary — this recovers names from before the gap."""
        names = set()
        for node_name, logger_name in self.ring.node_identities():
            names |= node_identity_names(node_name, logger_name)
        return names

    def _init_console_colors(self):
        """Set self.console_fg/console_bg to the exact DendROS brand colors when the
        terminal supports palette reprogramming (curses.init_color()/can_change_color()).

        The standard xterm-256 quantization (quantize_rgb_to_256()) renders brand blue
        (0,75,107) as a visibly teal-shifted color -- its nearest 256-cube entry is
        (0,95,95), equal green/blue, which reads as cyan/teal rather than navy. Reprogramming
        two reserved palette slots to the exact RGB (same technique other curses TUIs use for
        accurate brand chrome) fixes that; falls back to the quantized approximation on
        terminals that can't change their palette — and since the slots' stock colors are already
        blue/orange (see _CONSOLE_*_COLOR_SLOT), terminals that silently ignore the
        reprogramming still render the console legibly."""
        curses = self.curses
        try:
            if curses.can_change_color() and curses.COLORS >= 256:
                curses.init_color(_CONSOLE_BG_COLOR_SLOT, *_rgb_to_curses_scale(_DENDROS_BLUE))
                curses.init_color(_CONSOLE_FG_COLOR_SLOT, *_rgb_to_curses_scale(_DENDROS_ORANGE))
                self.console_bg = _CONSOLE_BG_COLOR_SLOT
                self.console_fg = _CONSOLE_FG_COLOR_SLOT
                return
        except curses.error:
            pass
        # No palette support at all: the same slots, unprogrammed, are still the closest
        # blue/orange (plain quantization would pick teal 23 for the blue).
        self.console_bg = _CONSOLE_BG_COLOR_SLOT
        self.console_fg = _CONSOLE_FG_COLOR_SLOT

    def _console_h(self):
        return 1 if (self.console_active or self.console_error is not None) else 0

    def _log_height(self, max_y):
        return max(1, max_y - self.banner_h - self._console_h())

    def _reset_view_after_filter_change(self):
        # Tail-relative row offsets mean nothing across a filter change: snap to the tail
        # and re-baseline _sync_pin() directly.
        self.view_offset = 0
        self.sel_anchor = None
        self.sel_cursor = None
        self.last_tail_growth = self.ring.tail_growth()

    def _show_console_error(self, msg):
        self.console_error = msg
        self.console_error_at = time.monotonic()

    def _apply_console_command(self, raw_text):
        """Dispatch one console command line. Shared by the local Enter-key submission and
        the remote mailbox poll — deliberately never touches console_active itself, so a
        remote command can't close a bar the local user is still typing into; only the
        local key-dispatch caller decides whether to close the bar on success."""
        cmd, arg = parse_console_command(raw_text)
        if cmd is None:
            return True  # empty submit: silent dismiss, not an error
        handler_name = self._COMMAND_HANDLERS.get(cmd)
        if handler_name is None:
            self._show_console_error(f'unknown command: {cmd}')
            return False
        return getattr(self, handler_name)(arg)

    def _console_key(self, ch):
        """One key while the console bar is open. Tab/Shift+Tab complete via self.completer
        (lib/console_spec.py); every other edit resets the completion cycle."""
        curses = self.curses
        if ch == 9:
            self.console_buffer = self.completer.tab(self.console_buffer, self.known_nodes,
                                                     muted_nodes=self.muted_nodes)
            return
        if ch == 27:
            result = read_escape_sequence(self.scr, self.curses)  # drains trailing bytes too
            if result is not None and result[0] == 'nav':
                if result[1] == 'backtab':
                    self.console_buffer = self.completer.tab(self.console_buffer, self.known_nodes,
                                                             backwards=True,
                                                             muted_nodes=self.muted_nodes)
                return  # arrows/PageUp/... don't close the bar mid-typing
        self.completer.reset()
        if ch in (10, 13, curses.KEY_ENTER):
            text = self.console_buffer
            self.console_buffer = ''
            if self._apply_console_command(text):
                self.console_active = False
        elif ch in (27, ord('\\')):
            # Bare Esc (or a mouse event) and \ cancel, symmetric with \ opening the bar. No
            # command syntax needs a literal backslash in its argument (node names are
            # restricted to [a-zA-Z0-9_./-]), so nothing is lost treating it as close.
            self.console_active = False
            self.console_buffer = ''
            self.console_error = None
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.console_buffer = self.console_buffer[:-1]
        elif 32 <= ch <= 126:
            self.console_buffer += chr(ch)

    def _check_remote_command(self):
        if self.review:
            return False  # `dendros reopen` viewer: the mailbox belongs to live launches
        now = time.monotonic()
        if now - self.last_command_check < 1.0:
            return False
        self.last_command_check = now
        text = pop_tui_command()
        if text is not None:
            self._apply_console_command(text)
            return True
        return False

    def _cmd_focus(self, arg):
        node_name = canonical_node_name(arg.strip())
        if not node_name:
            self._show_console_error('focus: node name required')
            return False
        if node_name not in self.known_nodes:
            self._show_console_error(f'focus: unknown node "{node_name}"')
            return False
        self.filter_node = node_name
        self.mode_stack = push_mode(self.mode_stack, 'focus')
        self._apply_filters()
        return True

    def _cmd_mute(self, arg):
        # Not a mode: no mode_stack entry, so Esc never undoes it — only `unmute` (one node or
        # `all`) and `clear` do. muted_nodes is mutated in place (shared with run_tui()'s
        # session dict, see _TuiSession.__init__).
        node_name = canonical_node_name(arg.strip())
        if not node_name:
            self._show_console_error('mute: node name required')
            return False
        if node_name not in self.known_nodes:
            self._show_console_error(f'mute: unknown node "{node_name}"')
            return False
        if node_name in self.muted_nodes:
            self._show_console_error(f'mute: "{node_name}" is already muted')
            return False
        self.muted_nodes.add(node_name)
        self._apply_filters()
        return True

    def _cmd_unmute(self, arg):
        node_name = canonical_node_name(arg.strip())
        if not node_name:
            self._show_console_error('unmute: node name or "all" required')
            return False
        if node_name == 'all':
            # Keyword wins over a node literally named "all" (still unmuted by this, too).
            if not self.muted_nodes:
                self._show_console_error('unmute: nothing is muted')
                return False
            self.muted_nodes.clear()  # in place: shared with the session dict
            self._apply_filters()
            return True
        if node_name not in self.muted_nodes:
            self._show_console_error(f'unmute: "{node_name}" is not muted')
            return False
        self.muted_nodes.discard(node_name)
        self._apply_filters()
        return True

    def _cmd_grep(self, arg):
        # Live filter on line text: lines arriving later that match show up too, so zero
        # current matches is not an error (e.g. waiting for "goal reached"). A bare `grep`
        # drops just the grep filter, keeping any focus.
        query = arg.strip()
        if not query and self.grep_query is None:
            self._show_console_error('grep: text required')
            return False
        self.grep_query = query or None
        if query:
            self.mode_stack = push_mode(self.mode_stack, 'grep')
        else:
            self.mode_stack = drop_mode(self.mode_stack, 'grep')
        self._apply_filters()
        return True

    def _cmd_level(self, arg):
        # `level warn` = WARN and worse; lines without a [LEVEL] (tracebacks, prints) always
        # stay visible. A bare `level` drops just the level filter, like a bare `grep`.
        if not arg.strip():
            if self.min_level is None:
                self._show_console_error(f'level: one of {"|".join(LEVEL_NAMES)} required')
                return False
            self.min_level = None
            self.mode_stack = drop_mode(self.mode_stack, 'level')
        else:
            level = parse_level(arg)
            if level is None:
                self._show_console_error(f'level: expected {"|".join(LEVEL_NAMES)}, got "{arg.strip()}"')
                return False
            self.min_level = level
            self.mode_stack = push_mode(self.mode_stack, 'level')
        self._apply_filters()
        return True

    def _cmd_clear(self, arg):
        # Back to normal view: drops every filter (focus, level, grep), every mute, and any
        # active find.
        self.filter_node = None
        self.muted_nodes.clear()  # in place: shared with the session dict
        self.grep_query = None
        self.min_level = None
        self._find_clear()
        self.mode_stack = []
        self._apply_filters()
        return True

    def _escape_mode(self):
        """Bare Esc (console closed): exit the most recently entered mode — find, grep or
        level/focus — leaving any earlier ones active. No-op when no mode is active."""
        if not self.mode_stack:
            return
        mode = self.mode_stack[-1]
        if mode == 'find':
            self._find_clear()  # drops 'find' from mode_stack itself
            return
        self.mode_stack = self.mode_stack[:-1]
        if mode == 'grep':
            self.grep_query = None
        elif mode == 'level':
            self.min_level = None
        elif mode == 'focus':
            self.filter_node = None
        self._apply_filters()

    def _apply_filters(self):
        # Rebuild the whole filter stack from per-command state, so filters compose.
        self.ring.set_filter(build_filter(self.filter_node, self.grep_query, self.min_level,
                                          self.muted_nodes))
        self._reset_view_after_filter_change()
        self._find_after_filter_change()
        self.console_error = None

    def _filter_status(self):
        return format_filter_status(self.filter_node, self.grep_query, self.min_level)

    def _mute_status(self):
        return format_mute_status(self.muted_nodes)
