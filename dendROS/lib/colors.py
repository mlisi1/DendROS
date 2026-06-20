"""ANSI color resolution utilities."""

import re

RESET = '\033[0m'
_ANSI_RE = re.compile(r'\033\[[0-9;]*m')
_HEX_RE = re.compile(r'^(@?)#([0-9a-fA-F]{6})$')

_COLOR_CODES = {
    'black': 30, 'red': 31, 'green': 32, 'yellow': 33,
    'blue':  34, 'magenta': 35, 'cyan': 36, 'white':  37,
}

# Extended named colors resolved as 24-bit truecolor. bold works; light/dark are ignored.
_HEX_ALIASES = {
    # reds / pinks
    'crimson':   'DC143C',
    'maroon':    '800000',
    'rose':      'FF007F',
    'pink':      'FF69B4',
    'coral':     'FF7F50',
    'salmon':    'FA8072',
    # oranges / yellows
    'orange':    'FFA500',
    'amber':     'FFBF00',
    'gold':      'FFD700',
    # greens
    'lime':      '32CD32',
    'mint':      '3EB489',
    'olive':     '808000',
    'teal':      '008080',
    'turquoise': '40E0D0',
    # blues
    'sky':       '87CEEB',
    'azure':     '007FFF',
    'navy':      '000080',
    # purples
    'lavender':  '967BB6',
    'purple':    '9370DB',
    'violet':    'EE82EE',
    'lilac':     'C8A2C8',
    'indigo':    '4B0082',
    # neutrals
    'brown':     'A0522D',
    'grey':      '808080',
    'gray':      '808080',
}


def _ansi(code):
    return f'\033[{code}m'


def _hex_to_ansi(hex6, bold=False):
    """Convert a 6-digit hex string to a 24-bit ANSI SGR code string."""
    r = int(hex6[0:2], 16)
    g = int(hex6[2:4], 16)
    b = int(hex6[4:6], 16)
    base = f'38;2;{r};{g};{b}'
    return f'1;{base}' if bold else base


def _resolve_color(value):
    """Convert a color value to an ANSI SGR string.

    Accepts:
      Raw ANSI codes:       "34;1", "92"
      Hex truecolor:        "#FF6600"            (24-bit color, normal)
                            "@#FF6600"           (24-bit color, bold)
                            "bold #FF6600"       (same as @#FF6600)
      Named colors:         "yellow", "light blue", "dark red", "bold green"
                            "bold light cyan"
    """
    s = str(value).strip()
    sl = s.lower()

    if re.match(r'^[0-9;]+$', sl):
        return sl

    m = _HEX_RE.match(sl)
    if m:
        return _hex_to_ansi(m.group(2), bold=m.group(1) == '@')

    words = sl.split()
    bold  = 'bold'  in words
    light = 'light' in words or 'bright' in words
    dark  = 'dark'  in words or 'dim'    in words

    for word in words:
        m = _HEX_RE.match(word)
        if m:
            return _hex_to_ansi(m.group(2), bold=bold)

    base_code = next((_COLOR_CODES[w] for w in words if w in _COLOR_CODES), None)
    if base_code is None:
        alias_hex = next((_HEX_ALIASES[w] for w in words if w in _HEX_ALIASES), None)
        if alias_hex is not None:
            return _hex_to_ansi(alias_hex, bold=bold)
        return sl

    if light:
        parts = [str(base_code + 60)]
        if bold:
            parts.append('1')
    else:
        parts = [str(base_code)]
        if dark:
            parts.append('2')
        elif bold:
            parts.append('1')

    return ';'.join(parts)


def make_dim(code):
    """Return a dim variant of an ANSI SGR code: strips bold (1), adds dim (2)."""
    parts = [p for p in code.split(';') if p and p != '1']
    if '2' not in parts:
        parts.append('2')
    return ';'.join(parts) if parts else '2'
