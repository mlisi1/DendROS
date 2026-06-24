"""Keyword highlighting for DendROS — ANSI-aware post-processing pass."""

import re
import fnmatch

from lib.colors import _resolve_color, RESET


def build_keyword_highlights(highlight_list, default_ansi_code):
    """Convert a highlight: config list into (pattern, ansi_code) pairs.

    Each entry may have:
      word           — text to match (required)
      color          — explicit color; null/absent = use default_ansi_code
      bold           — bool; append ;1 to the resolved code
      inverted       — bool; append ;7 (reverse video)
      case_sensitive — bool; default False
      regex          — bool; treat word as regex; default False (auto-escaped)
    """
    result = []
    for h in (highlight_list or []):
        word = h.get('word')
        if not word:
            continue

        raw_color = h.get('color')
        if raw_color:
            code = _resolve_color(str(raw_color))
        else:
            code = default_ansi_code or ''

        if h.get('bold') and '1' not in code.split(';'):
            code = f'{code};1' if code else '1'
        if h.get('inverted') and '7' not in code.split(';'):
            code = f'{code};7' if code else '7'

        case_sensitive = bool(h.get('case_sensitive', False))
        is_regex = bool(h.get('regex', False))
        pat_str = str(word) if is_regex else re.escape(str(word))
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(pat_str, flags)
        except re.error:
            continue

        if code:
            result.append((pattern, code))
    return result


def resolve_node_keywords(node_name, keyword_map):
    """Return keyword highlights for node_name using the same 4-tier lookup as resolve_node."""
    if not keyword_map:
        return []
    if node_name in keyword_map:
        return keyword_map[node_name]
    basename = node_name.rsplit('/', 1)[-1]
    if basename in keyword_map:
        return keyword_map[basename]
    for pattern, kws in keyword_map.items():
        if fnmatch.fnmatch(node_name, pattern):
            return kws
    for pattern, kws in keyword_map.items():
        if fnmatch.fnmatch(basename, pattern):
            return kws
    return []


def apply_keyword_highlights(colorized_line, highlights):
    """Post-process a colorized line, highlighting keywords without breaking ANSI codes.

    Splits the line into ANSI-escape tokens and plain-text tokens. Keywords are
    only matched in plain-text tokens; after each match the surrounding color is
    restored so existing colorization is not disrupted.
    """
    if not highlights:
        return colorized_line

    tokens = re.split(r'(\033\[[0-9;]*m)', colorized_line)
    active_code = None
    result = []

    for tok in tokens:
        if tok.startswith('\033['):
            code = tok[2:-1]
            active_code = None if (code == '' or code == '0') else code
            result.append(tok)
        else:
            restore = (f'{RESET}\033[{active_code}m' if active_code else RESET)
            text = tok
            for pattern, kw_code in highlights:
                text = pattern.sub(
                    lambda m, kc=kw_code, r=restore: f'\033[{kc}m{m.group(0)}{r}',
                    text,
                )
            result.append(text)

    return ''.join(result)
