#!/usr/bin/env python3
"""DendROS interactive config tool — manage global defaults via a terminal UI."""

import curses
import os
import sys
import textwrap
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.colors import DENDROS_TAG

try:
    import yaml
except ImportError:
    print(f'{DENDROS_TAG} PyYAML required: pip3 install pyyaml', file=sys.stderr)
    sys.exit(1)

from lib.global_config import get_global_config_path, DEFAULTS, load_global_config, save_global_config
from lib.logo import (
    _LOGO_W, _LOGO_ROWS, _LOGO_MIN_W,
    _HUE_STEP, _HUE_DELAY,
    draw_logo_ansi,
)
from lib.config_fields import _TAB_ORDER, _DESCS, _fields_for_tab

_VAL_LABEL = {True: "on", False: "off", None: "null"}

# curses color pair indices
_CP_HEADER = 1
_CP_SEL    = 2
_CP_VAL    = 3
_CP_DIM    = 4
_CP_OK     = 5
_CP_WARN   = 6

_UNCHANGED = object()  # sentinel: text editor was cancelled

# Local alias: tests import _DEFAULTS from this module; canonical definition is lib.global_config.DEFAULTS.
_DEFAULTS = DEFAULTS


# ── curses helpers ────────────────────────────────────────────────────────────

def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_CP_HEADER, curses.COLOR_MAGENTA, -1)
    curses.init_pair(_CP_SEL,    curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(_CP_VAL,    curses.COLOR_YELLOW,  -1)
    curses.init_pair(_CP_DIM,    -1,                   -1)
    curses.init_pair(_CP_OK,     curses.COLOR_GREEN,   -1)
    curses.init_pair(_CP_WARN,   curses.COLOR_YELLOW,  -1)


def _put(scr, row, col, text, attr=0):
    h, w = scr.getmaxyx()
    if row < 0 or row >= h or col < 0 or col >= w:
        return
    try:
        scr.addstr(row, col, text[:max(0, w - col)], attr)
    except curses.error:
        pass


def _val_str(v):
    return _VAL_LABEL.get(v, str(v))


def _draw_vline(scr, col, start_row, end_row):
    h = scr.getmaxyx()[0]
    for r in range(start_row, min(end_row, h - 1)):
        _put(scr, r, col, '│', curses.color_pair(_CP_DIM) | curses.A_DIM)


# ── inline text editor ────────────────────────────────────────────────────────

def _edit_text(scr, prompt, current):
    """Single-line inline editor at the bottom. Returns new value or _UNCHANGED."""
    h, w = scr.getmaxyx()
    row_hint  = h - 4
    row_input = h - 3
    buf = list("" if current is None else str(current))
    pos = len(buf)
    curses.curs_set(1)

    while True:
        _put(scr, row_hint,  0, " " * (w - 1))
        _put(scr, row_input, 0, " " * (w - 1))
        _put(scr, row_hint, 2,
             "Enter confirm   Esc cancel   empty / 'null' → null",
             curses.color_pair(_CP_DIM) | curses.A_DIM)
        text  = "".join(buf)
        label = f" {prompt}: "
        _put(scr, row_input, 0,
             (label + text).ljust(w - 1),
             curses.color_pair(_CP_VAL) | curses.A_BOLD)
        try:
            scr.move(row_input, min(len(label) + pos, w - 1))
        except curses.error:
            pass
        scr.refresh()

        key = scr.getch()
        if key in (10, 13, curses.KEY_ENTER):
            curses.curs_set(0)
            result = "".join(buf).strip()
            return None if result in ("", "null") else result
        elif key == 27:
            curses.curs_set(0)
            return _UNCHANGED
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if pos > 0:
                buf.pop(pos - 1)
                pos -= 1
        elif key == curses.KEY_DC:
            if pos < len(buf):
                buf.pop(pos)
        elif key == curses.KEY_LEFT:
            pos = max(0, pos - 1)
        elif key == curses.KEY_RIGHT:
            pos = min(len(buf), pos + 1)
        elif key == curses.KEY_HOME:
            pos = 0
        elif key == curses.KEY_END:
            pos = len(buf)
        elif 32 <= key <= 126:
            buf.insert(pos, chr(key))
            pos += 1


# ── main TUI loop ─────────────────────────────────────────────────────────────

def _draw_tab_bar(scr, row, fc, w, cur_tab):
    """Render the tab strip. Falls back to a compact "‹ n/N Label ›" indicator
    when the full set of tab labels doesn't fit the available width — same
    graceful-degradation spirit as the side logo's _LOGO_MIN_W cutoff.
    """
    avail_w = w - fc - 2
    full_labels = [f"{i + 1}:{lbl}" for i, (_, lbl) in enumerate(_TAB_ORDER)]
    full_width  = sum(len(l) + 3 for l in full_labels) - 3

    if full_width <= avail_w:
        col = fc
        for i, lbl in enumerate(full_labels):
            is_cur = (i == cur_tab)
            txt  = f"[{lbl}]" if is_cur else f" {lbl} "
            attr = (curses.color_pair(_CP_SEL) | curses.A_BOLD) if is_cur else (curses.color_pair(_CP_DIM) | curses.A_DIM)
            _put(scr, row, col, txt, attr)
            col += len(txt) + 1
    else:
        _, cur_label = _TAB_ORDER[cur_tab]
        compact = f"‹ {cur_tab + 1}/{len(_TAB_ORDER)} {cur_label} ›"
        _put(scr, row, fc, compact[:avail_w], curses.color_pair(_CP_SEL) | curses.A_BOLD)


def _run(scr):
    if curses.has_colors():
        _init_colors()
    curses.curs_set(0)
    scr.keypad(True)
    scr.timeout(50)

    cfg        = load_global_config()
    dirty      = False
    cur_tab    = 0
    sel        = 0
    status     = ("", 0)
    hue_offset = 0.0
    open_time  = time.monotonic()

    while True:
        scr.erase()
        h, w = scr.getmaxyx()

        use_logo = (w >= _LOGO_MIN_W)
        fc = _LOGO_W + 2 if use_logo else 0

        tag   = "  [unsaved]" if dirty else ""
        brand = "  DendROS Config"
        path  = f"  {get_global_config_path()}"
        gap   = max(0, w - len(brand) - len(path) - len(tag))
        _put(scr, 0, 0,
             (brand + path + " " * gap + tag)[:w],
             curses.color_pair(_CP_HEADER) | curses.A_BOLD)

        if use_logo:
            _draw_vline(scr, _LOGO_W, start_row=1, end_row=1 + _LOGO_ROWS + 1)

        tab_id, tab_label = _TAB_ORDER[cur_tab]
        fields = _fields_for_tab(tab_id)
        sel = min(sel, len(fields) - 1)

        _draw_tab_bar(scr, 1, fc, w, cur_tab)
        try:
            scr.hline(2, fc, curses.ACS_HLINE, max(0, w - fc),
                      curses.color_pair(_CP_DIM) | curses.A_DIM)
        except curses.error:
            pass

        for i, f in enumerate(fields):
            row    = 3 + i
            val    = cfg[f.key]
            is_sel = (i == sel)
            prefix = " ► " if is_sel else "   "
            row_attr = (curses.color_pair(_CP_SEL) | curses.A_BOLD) if is_sel else 0

            _put(scr, row, fc,     prefix,          row_attr)
            _put(scr, row, fc + 3, f"{f.label:<22}",  row_attr)

            col = fc + 26
            if f.kind == "cycle" and f.opts:
                for opt in f.opts:
                    is_cur   = (str(opt) == str(val))
                    opt_txt  = f"[{_val_str(opt)}]" if is_cur else _val_str(opt)
                    opt_attr = (curses.color_pair(_CP_VAL) | curses.A_BOLD) if is_cur else (curses.color_pair(_CP_DIM) | curses.A_DIM)
                    _put(scr, row, col, opt_txt, opt_attr)
                    col += len(opt_txt) + 2
            else:
                val_txt  = _val_str(val)
                val_attr = (curses.color_pair(_CP_VAL) | curses.A_BOLD) if is_sel else curses.color_pair(_CP_VAL)
                _put(scr, row, col, val_txt, val_attr)

        sep_row  = 3 + len(fields) + 1
        desc_row = sep_row + 1
        try:
            scr.hline(sep_row, fc, curses.ACS_HLINE, max(0, w - fc),
                      curses.color_pair(_CP_DIM) | curses.A_DIM)
        except curses.error:
            pass
        key_sel = fields[sel].key
        max_desc_w = max(10, w - fc - 4)
        desc_end_row = desc_row
        for line in _DESCS.get(key_sel, ()):
            for wline in textwrap.wrap(line, max_desc_w) or [line[:max_desc_w]]:
                _put(scr, desc_end_row, fc + 2, wline,
                     curses.color_pair(_CP_DIM) | curses.A_DIM)
                desc_end_row += 1

        st_row = desc_end_row + 1
        if status[0]:
            _put(scr, st_row, fc + 2, status[0],
                 curses.color_pair(status[1]) | curses.A_BOLD)

        hints = "  ↑↓ field   ←→/Space cycle   Tab/h l tab   1-9 jump   e edit   s save   q quit"
        _put(scr, h - 1, 0, hints[:w - 1].ljust(w - 1), curses.A_REVERSE | curses.A_DIM)

        scr.refresh()
        if use_logo:
            draw_logo_ansi(start_row=1, hue_offset=hue_offset)

        key = scr.getch()
        if key == -1:
            if use_logo and time.monotonic() - open_time >= _HUE_DELAY:
                hue_offset = (hue_offset + _HUE_STEP) % 1.0
            continue

        status = ("", 0)
        field = fields[sel]

        if key in (curses.KEY_UP, ord('k')):
            sel = max(0, sel - 1)

        elif key in (curses.KEY_DOWN, ord('j')):
            sel = min(len(fields) - 1, sel + 1)

        elif key in (9, ord('l')):
            cur_tab = (cur_tab + 1) % len(_TAB_ORDER)
            sel = 0

        elif key in (curses.KEY_BTAB, ord('h')):
            cur_tab = (cur_tab - 1) % len(_TAB_ORDER)
            sel = 0

        elif ord('1') <= key <= ord('9'):
            idx = key - ord('1')
            if idx < len(_TAB_ORDER):
                cur_tab = idx
                sel = 0

        elif key in (ord(' '), curses.KEY_RIGHT, 10, 13, curses.KEY_ENTER):
            if field.kind == "cycle" and field.opts:
                cur_idx = next((i for i, o in enumerate(field.opts) if str(o) == str(cfg[field.key])), 0)
                cfg[field.key] = field.opts[(cur_idx + 1) % len(field.opts)]
                dirty = True
            else:
                result = _edit_text(scr, field.label, cfg[field.key])
                if result is not _UNCHANGED:
                    cfg[field.key] = result
                    dirty = True

        elif key == curses.KEY_LEFT:
            if field.kind == "cycle" and field.opts:
                cur_idx = next((i for i, o in enumerate(field.opts) if str(o) == str(cfg[field.key])), 0)
                cfg[field.key] = field.opts[(cur_idx - 1) % len(field.opts)]
                dirty = True

        elif key == ord('e'):
            result = _edit_text(scr, field.label, cfg[field.key])
            if result is not _UNCHANGED:
                cfg[field.key] = result
                dirty = True

        elif key == ord('s'):
            save_global_config(cfg)
            dirty  = False
            status = (f"Saved → {get_global_config_path()}", _CP_OK)

        elif key == curses.KEY_RESIZE:
            pass

        elif key in (ord('q'), 27):
            if dirty:
                _put(scr, h - 4, fc + 2,
                     "Save before quitting? [y/N] ",
                     curses.color_pair(_CP_WARN) | curses.A_BOLD)
                scr.refresh()
                scr.timeout(-1)
                confirm = scr.getch()
                scr.timeout(50)
                if confirm in (ord('y'), ord('Y')):
                    save_global_config(cfg)
            break


def main():
    try:
        curses.wrapper(_run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
