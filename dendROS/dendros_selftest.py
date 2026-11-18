#!/usr/bin/env python3
"""`dendros test`: check that DendROS can run here, open the TUI once, and print color charts
showing what this terminal can draw.

It does not run the unit tests. Checks and charts live in lib/selftest.py and
lib/color_charts.py (pure, unit-tested); this file adds the curses probe and the printing.
Exit code 1 if any check failed.
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import __version__
from lib import color_charts as charts
from lib import selftest as st
from lib.colors import DENDROS_TAG, set_ignore_bold
from lib.global_config import get_global_config_path, load_global_config

_PROBE_HOLD_MS = 2000


def probe_tui(hold_ms=_PROBE_HOLD_MS):
    """Open a curses session the way the launch TUI does, push every palette index through
    the TUI's own color-pair path (fit_color/PairCache) and console-color setup, draw a short
    preview and close. Returns a dict for selftest.curses_probe_checks()."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return {'skipped': 'not run: needs an interactive terminal'}
    try:
        import curses
        from lib.launch_tui_console import (_CONSOLE_BG_COLOR_SLOT, _TuiConsoleMixin,
                                            _rgb_to_curses_scale)
        from lib.colors import _DENDROS_BLUE
        from lib.tui_pure import PairCache
    except Exception as e:
        return {'error': f'import failed ({e})'}

    info = {}

    class _Probe(_TuiConsoleMixin):
        def __init__(self, curses_module):
            self.curses = curses_module

    def _main(scr):
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        probe = _Probe(curses)
        probe._init_console_colors()
        if probe.console_bg == _CONSOLE_BG_COLOR_SLOT and curses.COLORS >= 256:
            try:
                exact = curses.color_content(_CONSOLE_BG_COLOR_SLOT) == \
                    _rgb_to_curses_scale(_DENDROS_BLUE)
            except curses.error:
                exact = False
            info['console'] = 'exact' if exact else 'stock'
        else:
            info['console'] = 'base'

        pairs = PairCache(curses)
        for c in range(256):            # the path that crashed on 8-color terminals
            pairs.attr_for(fg=c)
            pairs.attr_for(bg=c)

        rows, cols = scr.getmaxyx()
        info.update(rows=rows, cols=cols, colors=curses.COLORS, pairs=curses.COLOR_PAIRS)
        chrome = pairs.attr_for(fg=probe.console_fg, bg=probe.console_bg, bold=True)
        _draw_probe(scr, curses, pairs, chrome, rows, cols)
        scr.timeout(hold_ms)
        scr.getch()

    try:
        curses.wrapper(_main)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}
    return info


def _draw_probe(scr, curses, pairs, chrome, rows, cols):
    def put(y, x, text, attr=0):
        if 0 <= y < rows and x < cols:
            try:
                scr.addstr(y, x, text[:max(0, cols - x - (1 if y == rows - 1 else 0))], attr)
            except curses.error:
                pass

    put(0, 0, ' dendros test: TUI probe'.ljust(cols), chrome)
    put(2, 2, 'The 256-color palette as the TUI draws it:')
    y = 4
    for start in range(0, 256, 32):
        for j in range(32):
            put(y, 2 + 2 * j, '  ', pairs.attr_for(bg=start + j))
        y += 1
    put(rows - 1, 0, ' closing in 2 s, or press any key '.ljust(cols - 1), chrome)
    scr.refresh()


def main(argv=None):
    ap = argparse.ArgumentParser(prog='dendros test', description=__doc__.splitlines()[0])
    ap.add_argument('--no-tui', action='store_true', help='skip opening the TUI')
    ap.add_argument('--no-colors', action='store_true', help='skip the color charts')
    args = ap.parse_args(argv)

    cfg = load_global_config()
    set_ignore_bold(cfg.get('ignore_bold', False))
    try:
        import yaml
    except ImportError:
        yaml = None

    checks = []

    def section(title, items):
        print(st.section_title(title))
        for c in items:
            print(st.format_check(c))
        checks.extend(items)

    install_dir = os.path.dirname(os.path.abspath(__file__))
    print(f'{DENDROS_TAG} \033[1mdendros test\033[0m  v{__version__}  \033[2m{install_dir}\033[0m')

    section('Dependencies', st.dependency_checks())

    from lib.config_loader import load_config
    config_path = get_global_config_path()
    section('Shell and config', [
        st.check_wrapper(),
        st.check_enabled(),
        st.check_config_dir(os.path.dirname(config_path)),
        *st.check_global_config(config_path, yaml),
        st.check_launch_mode(cfg, sys.stdout.isatty()),
        *st.check_package_configs(st.find_package_configs(), load_config),
    ])

    cols, rows = shutil.get_terminal_size()
    terminal = [st.check_term(),
                st.Check(st.INFO, 'size', f'{cols}x{rows}'),
                st.truecolor_check()]
    if args.no_tui:
        terminal += st.curses_probe_checks({'skipped': 'skipped (--no-tui)'})
    else:
        terminal += st.curses_probe_checks(probe_tui())
    section('Terminal', terminal)

    if not args.no_colors:
        width = max(16, min(cols, 120) - 4)
        for title, rows_ in (
                ('Named colors (follow your terminal\'s palette)', charts.named_color_table()),
                ('Extended named colors', charts.extended_color_grid()),
                ('256-color palette (what the TUI can draw)', charts.palette_256()),
                ('24-bit gradients (smooth = full color support)', charts.truecolor_gradients(width)),
                ('Text attributes', charts.text_attributes()),
                ('Bold text vs. inverted badge (two shades? set ignore_bold: true)',
                 charts.bold_brightness_rows()),
                ('Preview with your settings', charts.sample_preview(cfg))):
            print(st.section_title(title))
            for r in rows_:
                print(r)

    text, code = st.summarize(checks)
    print(f'\n{DENDROS_TAG} {text}')
    return code


if __name__ == '__main__':
    sys.exit(main())
