"""Pure, curses-free description of the TUI `\\` console's commands — the single source of
truth behind both Tab completion in the console bar and the `\\help` overlay. Unit-tested
directly (test/unit/test_console_spec.py), including a check that every spec here has a
handler in lib/launch_tui_console.py's `_COMMAND_HANDLERS` and vice versa.

Adding a console command: one CommandSpec below (usage/summary/what its argument completes
from) alongside the usual `_cmd_<name>` method + `_COMMAND_HANDLERS` entry.
"""

from typing import NamedTuple, Optional

from lib.console_commands import LEVEL_NAMES, canonical_node_name


class CommandSpec(NamedTuple):
    name: str
    usage: str                 # shown in help, e.g. 'focus <node>'
    summary: str               # one line, shown in help
    arg_kind: Optional[str]    # what Tab completes the argument from:
                               # 'nodes' (several, space-separated) | 'unmuted_node' |
                               # 'muted_node' | 'level' | None


COMMANDS = (
    CommandSpec('focus', 'focus <node>...',
                "Show only these nodes' lines (launch process tag or logger name)", 'nodes'),
    CommandSpec('level', 'level <lvl>',
                'Show lines at debug|info|warn|error|fatal or worse (tracebacks always stay)', 'level'),
    CommandSpec('grep', 'grep <text>',
                'Show only lines containing text, highlighted (uppercase = case-sensitive)', None),
    CommandSpec('find', 'find <text>',
                'Jump to lines containing text; Tab/Shift+Tab step older/newer', None),
    CommandSpec('mute', 'mute <node>',
                "Hide a node's lines (not a mode: Esc keeps it; header shows the count)",
                'unmuted_node'),
    CommandSpec('unmute', 'unmute <node|all>', 'Show a muted node again, or every muted node',
                'muted_node'),
    CommandSpec('clear', 'clear', 'Drop every filter and mute, and end any find', None),
    CommandSpec('help', 'help', 'Show this help', None),
)
COMMAND_NAMES = tuple(spec.name for spec in COMMANDS)
_SPECS_BY_NAME = {spec.name: spec for spec in COMMANDS}

KEYS = (
    ('\\', 'Open the console (\\ or Esc closes it)'),
    ('Tab / Shift+Tab', 'In the console: complete / cycle. Otherwise: step find matches'),
    ('Up / Down', 'In the console: previous / next command'),
    ('Esc', 'Exit the most recent focus/level/grep/find, one per press'),
    ('PageUp/PageDown', 'Scroll (also mouse wheel, Up/Down)'),
    ('Home / End', 'Oldest line / follow the live tail'),
    ('Mouse drag', 'Select and copy to the clipboard'),
    ('q', 'Quit (once the launch has exited)'),
)

REMOTE_NOTE = ('From another shell: dendros focus|find|grep|level|mute|unmute|clear …  ·  '
               'dendros reopen')


# ── Tab completion ─────────────────────────────────────────────────────────────────

def _common_prefix(words):
    if not words:
        return ''
    first, last = min(words), max(words)
    i = 0
    while i < len(first) and i < len(last) and first[i] == last[i]:
        i += 1
    return first[:i]


def _match(prefix, candidates, smart_case):
    # Node names use smart case, like find/grep (a lowercase prefix matches
    # case-insensitively); command names and levels are case-insensitive outright, matching
    # how parse_console_command()/parse_level() read them.
    if smart_case and any(c.isupper() for c in prefix):
        return sorted(c for c in candidates if c.startswith(prefix))
    low = prefix.lower()
    return sorted(c for c in candidates if c.lower().startswith(low))


def completion_context(buffer, known_nodes=(), muted_nodes=()):
    """Split the console buffer into (head, prefix, candidates, smart_case): `head` is the
    fixed part kept verbatim, `prefix` the word being completed, `candidates` what it may
    become, `smart_case` whether an uppercase prefix means exact case (node names only).
    Candidates for a command name carry a trailing space (ready for the argument)."""
    stripped = buffer.lstrip()
    lead = buffer[:len(buffer) - len(stripped)]
    if ' ' not in stripped:
        return lead, stripped, [name + ' ' for name in COMMAND_NAMES], False
    cmd, rest = stripped.split(' ', 1)
    arg = rest.lstrip()
    head = buffer[:len(buffer) - len(arg)]
    spec = _SPECS_BY_NAME.get(cmd.lower())
    kind = spec.arg_kind if spec else None
    if kind == 'nodes':
        # Completes the last word; names already listed aren't offered again, and a
        # completed name gets a trailing space, ready for the next one.
        words = arg.split()
        if arg and not arg[-1].isspace():
            prefix = words.pop()
        else:
            prefix = ''
        head = buffer[:len(buffer) - len(prefix)]
        listed = {canonical_node_name(w) for w in words}
        pool = sorted(n + ' ' for n in set(known_nodes) - listed)
        return head, canonical_node_name(prefix), pool, True
    if kind == 'unmuted_node':
        return head, canonical_node_name(arg), sorted(set(known_nodes) - set(muted_nodes)), True
    if kind == 'muted_node':
        pool = sorted(muted_nodes) + (['all'] if muted_nodes else [])
        return head, canonical_node_name(arg), pool, True
    if kind == 'level':
        return head, arg, list(LEVEL_NAMES), False
    return head, arg, [], False


class Completer:
    """Tab/Shift+Tab state for the console bar. First Tab completes as far as the matches
    agree (bash-style); while it stays ambiguous, further Tabs cycle through the candidates
    (zsh-style), Shift+Tab backwards. Any other edit must call reset()."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.candidates = []     # current ambiguous matches, shown in the bar
        self.index = None        # cycled-to candidate, or None before the first cycle
        self._head = ''
        self._last_output = None

    def tab(self, buffer, known_nodes=(), backwards=False, muted_nodes=()):
        """Return the new buffer for a Tab (or Shift+Tab) press on `buffer`."""
        if buffer == self._last_output and len(self.candidates) > 1:
            n = len(self.candidates)
            if self.index is None:
                self.index = n - 1 if backwards else 0
            else:
                self.index = (self.index + (-1 if backwards else 1)) % n
            out = self._head + self.candidates[self.index]
            self._last_output = out
            return out

        head, prefix, pool, smart_case = completion_context(buffer, known_nodes, muted_nodes)
        matches = _match(prefix, pool, smart_case)
        self._head = head
        self.index = None
        if not matches:
            self.candidates = []
            self._last_output = None
            return buffer
        if len(matches) == 1:
            self.candidates = []
            out = head + matches[0]
        else:
            self.candidates = matches
            common = _common_prefix(matches)
            # Keep what was typed when the matches only agree case-insensitively.
            out = head + (common if len(common) > len(prefix) else prefix)
        self._last_output = out
        return out


# ── Command history ────────────────────────────────────────────────────────────────

class CommandHistory:
    """Up/Down recall in the console bar, bash-style. `entries` is the run-wide list of
    submitted commands, oldest-first (owned by the caller so it outlives one curses session);
    this object only tracks the browse position. Up from the line being typed saves it as a
    draft that Down past the newest entry brings back. Any edit must call reset()."""

    MAX_ENTRIES = 100

    def __init__(self, entries=None):
        self.entries = entries if entries is not None else []
        self.reset()

    def reset(self):
        self.index = None   # position in entries while browsing, None = not browsing
        self.draft = ''

    def add(self, text):
        """Record a submitted command (blank and repeat-of-the-last are skipped)."""
        text = text.strip()
        if text and (not self.entries or self.entries[-1] != text):
            self.entries.append(text)
            del self.entries[:-self.MAX_ENTRIES]
        self.reset()

    def older(self, buffer):
        """Buffer after Up: the previous entry (stays on the oldest once there)."""
        if not self.entries:
            return buffer
        if self.index is None:
            self.draft = buffer
            self.index = len(self.entries)
        self.index = max(0, self.index - 1)
        return self.entries[self.index]

    def newer(self, buffer):
        """Buffer after Down: the next entry, then the saved draft past the newest."""
        if self.index is None:
            return buffer
        self.index += 1
        if self.index >= len(self.entries):
            draft = self.draft
            self.reset()
            return draft
        return self.entries[self.index]


# ── Help overlay layout ───────────────────────────────────────────────────────────

def _wrap_words(text, width):
    width = max(1, width)
    lines, cur = [], ''
    for word in text.split():
        while len(word) > width:  # hard-split a word longer than the column
            if cur:
                lines.append(cur)
                cur = ''
            lines.append(word[:width])
            word = word[width:]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += ' ' + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or ['']


def help_rows(width):
    """The help overlay's content laid out for an inner width of `width` columns: a list of
    rows, each a list of (text, style) runs with style in 'section' | 'key' | 'desc' |
    'note'. Descriptions wrap under their own column, aligned past the widest key."""
    width = max(10, width)
    items = [('Commands', [(spec.usage, spec.summary) for spec in COMMANDS]),
             ('Keys', list(KEYS))]
    key_w = min(max(len(k) for _, pairs in items for k, _ in pairs), width // 2)
    desc_w = max(1, width - key_w - 2)
    rows = []
    for i, (section, pairs) in enumerate(items):
        if i:
            rows.append([])
        rows.append([(section, 'section')])
        for key, desc in pairs:
            for j, line in enumerate(_wrap_words(desc, desc_w)):
                k = key[:key_w] if j == 0 else ''
                rows.append([(k.ljust(key_w + 2), 'key'), (line, 'desc')])
    rows.append([])
    for line in _wrap_words(REMOTE_NOTE, width):
        rows.append([(line, 'note')])
    return rows
