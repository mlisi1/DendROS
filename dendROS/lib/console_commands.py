"""Pure, curses-free helpers backing the TUI launch mode's `\\`-console (see
lib/launch_tui_console.py). Node-identity matching and console command-line parsing — no
curses or thread dependency, so it's unit-tested directly (test/unit/test_console_commands.py).

Kept separate from lib/tui_pure.py: that module is generic terminal mechanics (ANSI parsing,
wrapping, selection, mouse/keyboard decoding) with no notion of what any console command
means; this module is where a growing family of console commands' own parsing/matching logic
belongs, so it doesn't pile back onto either lib/tui_pure.py or the curses-owning TUI files.

Node identity (node_name/logger_name) is NOT reverse-parsed from the final colorized/badged
text — that text's shape depends on tag_position, show_tag, show_timestamp, show_logger_name
and color_mode, all of which are per-package/per-user config, so no fixed regex can reliably
tell a badge apart from a process tag (e.g. tag_position: before puts the badge in the exact
leading-bracket position a process tag would otherwise occupy). Instead, dendROS_pipe.py's
own `_colorize()` already discovers node_name/logger_name authoritatively from the RAW
pre-colorization line (the same bidirectional discovery it already does for node_colors.yaml)
and threads them through the TUI's reader thread down to RingLog — see
lib/launch_tui.py::_drain_queue() and lib/tui_pure.py's RingLog.append()/set_filter().
"""

import functools
import re

from lib.tui_find import is_case_sensitive


def canonical_node_name(name):
    """Normalize a node name for matching. ROS graph/logger names in the root namespace
    print with a leading '/' (e.g. '/lidar_driver') but users naturally type a node name
    either with or without it — strip it so both forms are treated as the same node."""
    return name[1:] if name.startswith('/') else name


def node_identity_names(node_name, logger_name):
    """Return the set (possibly empty) of canonical name(s) identifying a line, given the
    node_name/logger_name discovered by dendROS_pipe.py's colorization pipeline. Both are
    included distinctly: composable nodes share their container's node_name (the launch
    process tag) but log under their own logger_name, and even for a non-composable node
    the two occasionally diverge (e.g. slam_toolbox launched as slam_node still logs as
    slam_toolbox) — a user should be able to focus by either."""
    names = set()
    if node_name:
        names.add(canonical_node_name(node_name))
    if logger_name:
        names.add(canonical_node_name(logger_name))
    return names


def line_matches_node(node_name, logger_name, target):
    """True if a line's discovered node_name/logger_name identifies `target`. `target` is
    expected to already be canonical_node_name()-normalized by the caller (the console
    command handlers do this once, up front)."""
    return target in node_identity_names(node_name, logger_name)


def focus_predicate(plain_text, node_name, logger_name, target):
    """RingLog.set_filter() predicate for `focus <target>` — matches on node identity, not
    line text. `plain_text` is unused but required by the predicate signature (see
    RingLog.set_filter()'s docstring in lib/tui_pure.py)."""
    return line_matches_node(node_name, logger_name, target)


def grep_predicate(plain_text, node_name, logger_name, query):
    """RingLog.set_filter() predicate for `grep <query>` — the counterpart to focus that
    matches on the displayed line text rather than node identity. Substring with the same
    smart case as `find` (lib/tui_find.py): case-insensitive unless the query has an
    uppercase letter. node_name/logger_name are unused but required by the signature."""
    if is_case_sensitive(query):
        return query in plain_text
    return query.lower() in plain_text.lower()


# ── `level` ──────────────────────────────────────────────────────────────────────
# Severity ranks, lowest first. Canonical names are what `level` stores and displays.
LEVEL_NAMES = ('debug', 'info', 'warn', 'error', 'fatal')
_LEVEL_RANKS = {name: rank for rank, name in enumerate(LEVEL_NAMES)}
_LEVEL_ALIASES = {'warning': 'warn'}
# First [LEVEL] bracket in the displayed text: node output (`[node-1] [WARN] [ts] …`, any
# tag_position/show_timestamp/show_logger_name combo keeps it) and launch-framework lines
# (`[ERROR] [talker-1]: process has died …`) alike. Message text comes after it, so a
# "[ERROR]" inside a message can't outrank the line's real level.
_LINE_LEVEL_RE = re.compile(r'\[(DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL)\]')


def parse_level(text):
    """Canonical level name for user input (case-insensitive, `warning` = `warn`), or None
    if it isn't a level."""
    name = text.strip().lower()
    name = _LEVEL_ALIASES.get(name, name)
    return name if name in _LEVEL_RANKS else None


def line_level(plain_text):
    """Severity rank of a displayed line, or None for lines that aren't ROS log records
    (tracebacks, print() output, DendROS's own alert lines)."""
    m = _LINE_LEVEL_RE.search(plain_text)
    if m is None:
        return None
    return _LEVEL_RANKS[parse_level(m.group(1))]


def level_predicate(plain_text, node_name, logger_name, min_level):
    """RingLog.set_filter() predicate for `level <min_level>`: lines at that severity or
    worse. Lines without a level always pass — a severity filter must never hide a
    traceback or crash output, which carry no [LEVEL] bracket."""
    rank = line_level(plain_text)
    return rank is None or rank >= _LEVEL_RANKS[min_level]


# ── `mute` / `unmute` ──────────────────────────────────────────────────────────────
# Not a mode (Esc never undoes it; `unmute <node|all>` and `clear` do): a set of canonical
# node names whose lines are hidden underneath every other filter. Persisted with the run
# for `dendros reopen`.

def mute_predicate(plain_text, node_name, logger_name, muted):
    """RingLog.set_filter() predicate hiding lines from muted nodes. Same identity rule as
    focus (process tag OR logger name): muting a container hides its components' lines too,
    muting a component's logger name hides only that component."""
    return not (node_identity_names(node_name, logger_name) & muted)


def format_mute_status(muted):
    """Header text while any node is muted, e.g. `2 nodes muted`, else None."""
    n = len(muted)
    if not n:
        return None
    return f'{n} node{"s" if n != 1 else ""} muted'


def build_filter(focus_node=None, grep_query=None, min_level=None, muted=None):
    """Combine the active console filters into one RingLog.set_filter() predicate (all must
    hold), or None when none are active. Each filtering command only updates its own state
    and the caller rebuilds the whole stack through here, so filters compose (e.g. focus +
    grep) instead of the last command overwriting the previous one's filter."""
    preds = []
    if muted:
        preds.append(functools.partial(mute_predicate, muted=frozenset(muted)))
    if focus_node:
        preds.append(functools.partial(focus_predicate, target=focus_node))
    if min_level:
        preds.append(functools.partial(level_predicate, min_level=min_level))
    if grep_query:
        preds.append(functools.partial(grep_predicate, query=grep_query))
    if not preds:
        return None
    if len(preds) == 1:
        return preds[0]
    return lambda plain, node_name, logger_name: all(p(plain, node_name, logger_name) for p in preds)


def format_filter_status(focus_node=None, grep_query=None, min_level=None):
    """Header chip text describing the active filter stack, e.g.
    `focus talker · level warn · grep "x"`, or None when unfiltered."""
    parts = []
    if focus_node:
        parts.append(f'focus {focus_node}')
    if min_level:
        parts.append(f'level {min_level}')
    if grep_query:
        parts.append(f'grep "{grep_query}"')
    return ' · '.join(parts) if parts else None


# ── Esc mode stack ─────────────────────────────────────────────────────────────────
# "Invasive" view modes (focus, level, grep, find) are remembered in activation order; bare Esc
# exits the most recent one, so stacked modes peel back one layer per press. Pure list
# helpers so the ordering rules are unit-tested; the TUI keeps the list on _TuiSession.

def push_mode(stack, mode):
    """Mark `mode` as the most recently activated. Re-activating an already-active mode
    (e.g. a second `grep` with new text) moves it to the top instead of duplicating it."""
    return [m for m in stack if m != mode] + [mode]


def drop_mode(stack, mode):
    """Remove `mode` (no-op if inactive) — when it's ended by anything other than Esc."""
    return [m for m in stack if m != mode]


def parse_console_command(text):
    """Split raw console input into (command, arg). `command` is lowercased; `arg` is
    everything after the first whitespace-separated token, stripped, or '' if there's no
    second token. Returns (None, '') for empty/whitespace-only input.

    Deliberately generic (command + raw remainder string) so a future command's argument
    grammar doesn't require changing this parser — each _cmd_* handler parses its own `arg`
    string further if it needs more than one token."""
    stripped = text.strip()
    if not stripped:
        return None, ''
    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ''
    return cmd, arg
