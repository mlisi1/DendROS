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
