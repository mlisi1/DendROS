#!/usr/bin/env python3
"""DendROS interactive config tool — manage global defaults via a terminal UI."""

import curses
import os
import sys
import textwrap
import time

try:
    import yaml
except ImportError:
    print("[dendROS] PyYAML required: pip3 install pyyaml", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.global_config import get_global_config_path, DEFAULTS, load_global_config, save_global_config
from lib.logo import (
    _LOGO_W, _LOGO_ROWS, _LOGO_MIN_W,
    _LOGO_LINES, _LOGO_PARSED,
    _shift_rgb, _render_logo_line, _make_title_line,
    _HUE_STEP, _HUE_DELAY,
    draw_logo_ansi,
)

# (key, display_label, kind, cycle_options)
_FIELDS = [
    ("color_mode",           "Color mode",            "cycle", ["tag_only", "full_line"]),
    ("show_group_tag",       "Show group tag",        "cycle", [True, False]),
    ("tag_position",         "Tag position",          "cycle", ["after", "before"]),
    ("tag_style",            "Tag style",             "cycle", ["normal", "inverted"]),
    ("unmatched_color",      "Unmatched color",       "text",  None),
    ("debug",                "Debug mode",            "cycle", [False, True]),
    ("config_merge",         "Config merge",          "cycle", [True, False]),
    ("colorize_launch_msgs", "Colorize launch msgs",  "cycle", [True, False]),
    ("unmatched_tag",        "Unmatched tag",         "text",  None),
    ("dim_unmatched",        "Dim unmatched",         "cycle", [False, True]),
    ("init_modify_build",    "Init: modify build",    "cycle", [True, False]),
    ("init_on_existing",     "Init: on existing",     "cycle", ["abort", "merge", "overwrite"]),
    ("init_color",           "Init: color",           "cycle", ["palette", "null"]),
    ("init_color_bold",      "Init: bold colors",     "cycle", [False, True]),
    ("init_label",           "Init: auto label",      "cycle", [False, True]),
    ("crash_alert",          "Crash alert",           "cycle", [False, True]),
    ("crash_alert_color",    "Alert color",           "cycle", ["node", "red"]),
    ("crash_alert_interval", "Alert interval (s)",    "text",  None),
    ("traceback_color",      "Traceback color",       "cycle", ["fancy", "red", "off"]),
]

_DESCS = {
    "color_mode": (
        "tag_only  — color [node-N] prefix and [TAG] badge only; preserves ROS 2"
        " severity colors (WARN=yellow, ERROR=red)",
        "full_line — strip embedded ANSI and color the entire line; cleaner but"
        " overrides severity colors",
    ),
    "show_group_tag": (
        "on  — show colored [LOC] / [NAV] badges next to the [node-N] prefix",
        "off — no badges; only the prefix itself is colored",
    ),
    "tag_position": (
        "after  — badge appears after the prefix: [node-N] [TAG] [INFO] …",
        "before — badge appears before the prefix: [TAG] [node-N] [INFO] …",
    ),
    "tag_style": (
        "normal   — [TAG] badge uses colored text on the default terminal background",
        "inverted — [TAG] badge uses colored background with empty letters (like crash alerts)",
    ),
    "unmatched_color": (
        "Tint for nodes not listed in any group.",
        "null = pass through unchanged.  Accepts: bold blue, #FF6600, 34;1, …",
    ),
    "debug": (
        "on  — print config summary and node→color map to stderr on startup",
        "off — silent.  DENDROS_DEBUG env var always overrides this setting.",
    ),
    "config_merge": (
        "on  — parse the launched package's launch file and merge dendROS.yaml configs"
        " from all referenced packages (primary package wins conflicts)",
        "off — only colorize nodes defined in the launched package's own dendROS.yaml",
    ),
    "colorize_launch_msgs": (
        "on  — color the [node-N] bracket in launch-framework lines"
        " ([INFO] [node-N]: process started …)",
        "off — leave launch-framework lifecycle lines untouched (pass through unchanged)",
    ),
    "unmatched_tag": (
        "Badge shown for nodes not listed in any group when unmatched_color is set.",
        "null = no badge.  Example: ? shows [?] next to the unmatched node prefix.",
    ),
    "dim_unmatched": (
        "on  — apply ANSI dim to unmatched node lines (only when unmatched_color is null)",
        "off — unmatched nodes pass through at full brightness",
    ),
    "init_modify_build": (
        "on  — `dendros init` automatically adds config/ install to CMakeLists.txt,"
        " setup.py, or setup.cfg as appropriate",
        "off — only create config/dendROS.yaml; leave build files untouched",
    ),
    "init_on_existing": (
        "abort     — `dendros init` stops with an error if config/dendROS.yaml already exists",
        "merge     — add newly found nodes to the existing config without removing anything",
        "overwrite — replace the existing config/dendROS.yaml entirely",
    ),
    "init_color": (
        "palette — assign distinct colors from the stock palette to each node group",
        "null    — set color: null for all groups (passthrough); fill in colors manually",
    ),
    "init_color_bold": (
        "off — use palette colors as-is (some may already be bold)",
        "on  — prefix every generated palette color with bold",
    ),
    "init_label": (
        "off — write label: \"\" for each group (entry is created; fill in manually)",
        "on  — auto-generate a short label from the package name (e.g. nav2_bringup → NB)",
    ),
    "crash_alert": (
        "on  — print an inline alert banner when a ROS 2 node dies unexpectedly",
        "off — no banner; node death appears only in the normal log stream",
    ),
    "crash_alert_color": (
        "node — color the dead node's name using its configured group color",
        "red  — always show the dead node's name in bold red regardless of group",
    ),
    "crash_alert_interval": (
        "Seconds between automatic alert reprints while nodes remain crashed.",
        "0 = print only once (on crash) + again when new nodes die. Default: 30.",
    ),
    "traceback_color": (
        "fancy — bold red header/exception, dim red frame lines (default)",
        "red   — entire traceback in bold red  |  off — no coloring (white)",
    ),
}

_VAL_LABEL = {True: "on", False: "off", None: "null"}

# curses color pair indices
_CP_HEADER = 1
_CP_SEL    = 2
_CP_VAL    = 3
_CP_DIM    = 4
_CP_OK     = 5
_CP_WARN   = 6

_UNCHANGED = object()  # sentinel: text editor was cancelled

# Keep _DEFAULTS as a local alias for backward compatibility with tests that
# import it directly from this module.  The canonical definition lives in lib.global_config.
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

def _run(scr):
    if curses.has_colors():
        _init_colors()
    curses.curs_set(0)
    scr.keypad(True)
    scr.timeout(50)

    cfg        = load_global_config()
    dirty      = False
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

        for i, (key, label, kind, opts) in enumerate(_FIELDS):
            row    = 2 + i
            val    = cfg[key]
            is_sel = (i == sel)
            prefix = " ► " if is_sel else "   "
            row_attr = (curses.color_pair(_CP_SEL) | curses.A_BOLD) if is_sel else 0

            _put(scr, row, fc,     prefix,          row_attr)
            _put(scr, row, fc + 3, f"{label:<22}",  row_attr)

            col = fc + 26
            if kind == "cycle" and opts:
                for opt in opts:
                    is_cur   = (str(opt) == str(val))
                    opt_txt  = f"[{_val_str(opt)}]" if is_cur else _val_str(opt)
                    opt_attr = (curses.color_pair(_CP_VAL) | curses.A_BOLD) if is_cur else (curses.color_pair(_CP_DIM) | curses.A_DIM)
                    _put(scr, row, col, opt_txt, opt_attr)
                    col += len(opt_txt) + 2
            else:
                val_txt  = _val_str(val)
                val_attr = (curses.color_pair(_CP_VAL) | curses.A_BOLD) if is_sel else curses.color_pair(_CP_VAL)
                _put(scr, row, col, val_txt, val_attr)

        sep_row  = 2 + len(_FIELDS) + 1
        desc_row = sep_row + 1
        try:
            scr.hline(sep_row, fc, curses.ACS_HLINE, max(0, w - fc),
                      curses.color_pair(_CP_DIM) | curses.A_DIM)
        except curses.error:
            pass
        key_sel = _FIELDS[sel][0]
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

        hints = "  ↑↓ navigate   Space/→ cycle   e edit text   s save   q quit"
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
        field_key, field_label, kind, opts = _FIELDS[sel]

        if key in (curses.KEY_UP, ord('k')):
            sel = max(0, sel - 1)

        elif key in (curses.KEY_DOWN, ord('j')):
            sel = min(len(_FIELDS) - 1, sel + 1)

        elif key in (ord(' '), curses.KEY_RIGHT, 10, 13, curses.KEY_ENTER):
            if kind == "cycle" and opts:
                cur_idx = next((i for i, o in enumerate(opts) if str(o) == str(cfg[field_key])), 0)
                cfg[field_key] = opts[(cur_idx + 1) % len(opts)]
                dirty = True
            else:
                result = _edit_text(scr, field_label, cfg[field_key])
                if result is not _UNCHANGED:
                    cfg[field_key] = result
                    dirty = True

        elif key == curses.KEY_LEFT:
            if kind == "cycle" and opts:
                cur_idx = next((i for i, o in enumerate(opts) if str(o) == str(cfg[field_key])), 0)
                cfg[field_key] = opts[(cur_idx - 1) % len(opts)]
                dirty = True

        elif key == ord('e'):
            result = _edit_text(scr, field_label, cfg[field_key])
            if result is not _UNCHANGED:
                cfg[field_key] = result
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
