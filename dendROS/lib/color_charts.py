"""`dendros test`, pure layer: the color charts it prints.

Every chart is a list of ANSI strings built from the same code paths DendROS uses
(_resolve_color(), colorize_line(), the TUI's quantize_rgb_to_256()), so what the terminal
shows here is what it will show for those config values. Unit-tested in test_selftest.py.
"""

import colorsys

from lib.colors import (RESET, _COLOR_CODES, _DENDROS_BLUE, _DENDROS_ORANGE, _HEX_ALIASES,
                        _resolve_color)
from lib.colorizers import PREFIX_RE, colorize_launch_msg, colorize_line, strip_log_metadata
from lib.tui_pure import quantize_rgb_to_256

_HALF_BLOCK = '▀'   # ▀ : fg paints the top half of the cell, bg the bottom half
_BLOCK = '██'


def _fg(rgb):
    return '\033[38;2;{};{};{}m'.format(*rgb)


def _bg(rgb):
    return '\033[48;2;{};{};{}m'.format(*rgb)


def named_color_table():
    """The 8 base names with each modifier, resolved as a config value would be, plus the
    normal and inverted [TAG] badge. These follow the terminal's own 16-color palette."""
    cols = ('', 'light', 'bold', 'dark')
    head = '  {:<10}'.format('name') + ''.join(f'{c or "plain":<10}' for c in cols[1:]) \
        + 'badge     inverted'
    rows = ['\033[2m' + head + RESET]
    for name in _COLOR_CODES:
        cells = []
        for mod in cols:
            code = _resolve_color(f'{mod} {name}'.strip())
            cells.append(f'\033[{code}m{name:<8}{RESET}  ')
        code = _resolve_color(name)
        badge = f'\033[{code}m[TAG]{RESET}     \033[{code};7m[TAG]{RESET}'
        rows.append('  ' + ''.join(cells) + badge)
    return rows


def extended_color_grid(per_row=4):
    """Extended names (24-bit): left swatch = exact color (classic mode, CLI), right swatch =
    how the TUI draws it (nearest of the 256-color palette)."""
    names, seen = [], set()
    for name, hx in _HEX_ALIASES.items():
        if hx not in seen:               # grey/gray share a value: show it once
            seen.add(hx)
            names.append('grey/gray' if name in ('grey', 'gray') else name)
    cells = []
    for name in names:
        hx = _HEX_ALIASES[name.split('/')[0]]
        rgb = (int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16))
        tui = quantize_rgb_to_256(*rgb)
        cells.append(f'{_fg(rgb)}{_BLOCK}{RESET}\033[38;5;{tui}m{_BLOCK}{RESET} {name:<11}')
    rows = ['\033[2m  (left: exact 24-bit color, right: as drawn in the TUI)' + RESET]
    for i in range(0, len(cells), per_row):
        rows.append('  ' + ''.join(cells[i:i + per_row]))
    return rows


def palette_256():
    """System colors 0-15 with their index, the 6x6x6 cube (one 36-wide row per red level)
    and the 24-step grey ramp — the colors the TUI can draw."""
    def cell(i, w):
        fg = 15 if i in (0, 1, 4, 5, 8, 12) else 0
        return f'\033[48;5;{i};38;5;{fg}m{i:^{w}}{RESET}'
    rows = ['  ' + ''.join(cell(i, 4) for i in range(8)),
            '  ' + ''.join(cell(i, 4) for i in range(8, 16))]
    for r in range(6):
        rows.append('  ' + ''.join(f'\033[48;5;{16 + 36 * r + j}m  ' for j in range(36)) + RESET)
    rows.append('  ' + ''.join(f'\033[48;5;{i}m   ' for i in range(232, 256)) + RESET)
    return rows


def _gradient_row(width, top, bottom):
    """One text row = two pixel rows: `top(t)`/`bottom(t)` give the RGB at t in [0, 1]."""
    out = []
    for x in range(width):
        t = x / max(1, width - 1)
        out.append(f'{_fg(top(t))}{_bg(bottom(t))}{_HALF_BLOCK}')
    return '  ' + ''.join(out) + RESET


def _hsv(h, s, v):
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h % 1.0, s, v))


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def truecolor_gradients(width):
    """24-bit gradients: hue (bright → deep), grey, brand blue → orange. Smooth = the
    terminal renders 24-bit color; visible steps = it approximates."""
    width = max(16, width)
    return [
        _gradient_row(width, lambda t: _hsv(t, 0.35, 1.0), lambda t: _hsv(t, 0.75, 1.0)),
        _gradient_row(width, lambda t: _hsv(t, 1.0, 1.0), lambda t: _hsv(t, 1.0, 0.7)),
        _gradient_row(width, lambda t: _hsv(t, 1.0, 0.45), lambda t: _hsv(t, 1.0, 0.25)),
        _gradient_row(width, lambda t: _lerp((0, 0, 0), (255, 255, 255), t),
                      lambda t: _lerp((0, 0, 0), (255, 255, 255), t)),
        _gradient_row(width, lambda t: _lerp(_DENDROS_BLUE, _DENDROS_ORANGE, t),
                      lambda t: _lerp(_DENDROS_BLUE, _DENDROS_ORANGE, t)),
    ]


def text_attributes():
    """SGR attributes DendROS relies on (bold, dim for unmatched/defaults, reverse for
    badges) and two it doesn't, so a terminal's support is visible at a glance."""
    attrs = (('1', 'bold'), ('2', 'dim'), ('3', 'italic'), ('4', 'underline'),
             ('7', 'reverse'), ('9', 'strike'))
    return ['  ' + '  '.join(f'\033[{c}m{name}{RESET}' for c, name in attrs)]


def bold_brightness_rows():
    """Bold text next to its inverted badge, per base color. Terminals that brighten bold
    foregrounds but not backgrounds show two shades — that's what `ignore_bold` is for."""
    cells = []
    for name, code in _COLOR_CODES.items():
        if name in ('black', 'white'):
            continue
        cells.append(f'\033[{code};1m{name}{RESET} \033[{code};1;7m[TAG]{RESET}')
    return ['  ' + '   '.join(cells)]


# A small launch, three groups + one launch-framework line, in rcutils' colorized format.
_SAMPLE = (
    ('cyan', 'NAV', '[controller_server-1] [INFO] [1763460000.120] [controller_server]: '
                    'Controller frequency set to 20.0Hz'),
    ('magenta', 'LOC', '[amcl-2] \033[33m[WARN] [1763460000.341] [amcl]: '
                       'AMCL cannot publish a pose or update the transform\033[0m'),
    ('green', 'SNS', '[lidar_driver-3] \033[31m[ERROR] [1763460000.502] [lidar_driver]: '
                     'Timed out waiting for a scan\033[0m'),
)
_SAMPLE_LAUNCH = ('cyan', '[INFO] [controller_server-1]: process started with pid [41213]')


def sample_preview(cfg):
    """Sample launch lines rendered with the user's global display settings."""
    tag_position = cfg.get('tag_position', 'before')
    tag_style = cfg.get('tag_style', 'normal')
    color_mode = cfg.get('color_mode', 'tag_only')
    show_tag = cfg.get('show_tag_launch', True)
    rows = []
    if cfg.get('colorize_launch_msgs', True):
        color, line = _SAMPLE_LAUNCH
        rows.append('  ' + colorize_launch_msg(line, _resolve_color(color), color_mode).rstrip('\n'))
    for color, label, line in _SAMPLE:
        m = PREFIX_RE.match(line)
        line = strip_log_metadata(line, m.end(), cfg.get('show_timestamp', True),
                                  cfg.get('show_logger_name', True))
        colored = colorize_line(line, _resolve_color(color), label, show_tag, color_mode,
                                tag_position, tag_style)
        rows.append('  ' + colored.rstrip('\n'))
    return rows
