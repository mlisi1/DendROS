#!/usr/bin/env python3
"""DendROS interactive config tool — manage global defaults via a terminal UI."""

import colorsys
import curses
import os
import re
import sys
import textwrap
import time

try:
    import yaml
except ImportError:
    print("[dendROS] PyYAML required: pip3 install pyyaml", file=sys.stderr)
    sys.exit(1)

GLOBAL_CONFIG_PATH = os.path.expanduser("~/.config/dendROS/defaults.yaml")

_DEFAULTS = {
    "color_mode":           "tag_only",
    "show_group_tag":       True,
    "tag_position":         "after",
    "unmatched_color":      None,
    "debug":                False,
    "config_merge":         True,
    "colorize_launch_msgs": True,
    "unmatched_tag":        None,
    "dim_unmatched":        False,
    "init_modify_build":    True,
    "init_on_existing":     "abort",
    "init_color":           "palette",
    "init_color_bold":      False,
    "init_label":           False,
}

# (key, display_label, kind, cycle_options)
# kind: "cycle" — Space/→/Enter advances through options
#       "text"  — Enter/e opens inline text editor
_FIELDS = [
    ("color_mode",           "Color mode",            "cycle", ["tag_only", "full_line"]),
    ("show_group_tag",       "Show group tag",        "cycle", [True, False]),
    ("tag_position",         "Tag position",          "cycle", ["after", "before"]),
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
}

_VAL_LABEL = {True: "on", False: "off", None: "null"}

# curses color pair indices
_CP_HEADER = 1
_CP_SEL    = 2
_CP_VAL    = 3
_CP_DIM    = 4
_CP_OK     = 5
_CP_WARN   = 6

# logo layout constants
_LOGO_W     = 42    # columns — used as field-area left margin when logo is shown
_LOGO_ROWS  = 21    # rows the art occupies
_LOGO_MIN_W = 96    # minimum terminal width required to show the logo

_UNCHANGED = object()  # sentinel: text editor was cancelled

# ── logo: 24-bit half-block ANSI art (42×21, from res/RBGHZ0000_.png) ────────
# Rendered with ▀/▄ Unicode half-blocks + 24-bit foreground/background colors.
# Written directly to stdout after each scr.refresh(); curses never touches
# this region so the art persists without flicker between frames.
_LOGO_LINES = [
    '',
    '',
    '',
    '                           \x1b[38;2;19;33;38m▄\x1b[0m\x1b[38;2;3;6;7m▄\x1b[0m\x1b[38;2;17;29;34m▄\x1b[0m',
    '                        \x1b[38;2;12;19;24m▄\x1b[0m\x1b[38;2;24;42;47m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;255;194;93m▀\x1b[0m\x1b[38;2;34;68;37m\x1b[48;2;230;126;0m▀\x1b[0m\x1b[38;2;155;132;65m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;82;67;25m\x1b[48;2;219;124;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;235;133;0m▀\x1b[0m\x1b[38;2;24;45;52m\x1b[48;2;149;109;35m▀\x1b[0m\x1b[38;2;14;27;24m\x1b[48;2;27;25;9m▀\x1b[0m\x1b[38;2;9;22;9m▄\x1b[0m\x1b[38;2;16;18;7m▄\x1b[0m\x1b[38;2;0;0;0m▄\x1b[0m\x1b[38;2;0;0;0m▄\x1b[0m\x1b[38;2;18;28;33m▄\x1b[0m',
    '                     \x1b[38;2;0;0;0m▄\x1b[0m\x1b[38;2;22;39;45m▄\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;229;143;6m▀\x1b[0m\x1b[38;2;255;193;87m\x1b[48;2;230;126;0m▀\x1b[0m\x1b[38;2;230;126;0m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;45;91;92m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;230;130;0m\x1b[48;2;133;77;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;230;130;0m▀\x1b[0m\x1b[38;2;230;130;0m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;224;127;0m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;235;133;0m\x1b[48;2;214;121;0m▀\x1b[0m\x1b[38;2;162;95;2m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;199;116;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;16;30;27m▄\x1b[0m',
    '              \x1b[38;2;11;17;20m▄\x1b[0m\x1b[38;2;23;43;49m▄\x1b[0m\x1b[38;2;1;3;4m▄\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;23;41;44m\x1b[48;2;25;27;9m▀\x1b[0m\x1b[38;2;22;46;49m\x1b[48;2;67;69;28m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;36;66;71m▀\x1b[0m\x1b[38;2;4;10;11m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;90;64;12m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;219;124;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;112;65;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;209;118;0m▀\x1b[0m\x1b[38;2;224;127;0m\x1b[48;2;179;101;0m▀\x1b[0m\x1b[38;2;224;127;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;90;56;1m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;28;41;53m▀\x1b[0m',
    '           \x1b[38;2;0;0;0m▄\x1b[0m\x1b[38;2;14;27;32m\x1b[48;2;2;7;8m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;46;74;87m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;10;22;26m▀\x1b[0m\x1b[38;2;124;89;19m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;254;168;32m\x1b[48;2;184;101;0m▀\x1b[0m\x1b[38;2;255;165;32m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;255;145;0m\x1b[48;2;230;126;0m▀\x1b[0m\x1b[38;2;235;129;0m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;90;53;1m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;47;31;4m▀\x1b[0m\x1b[38;2;8;8;2m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;230;130;0m\x1b[48;2;204;116;0m▀\x1b[0m\x1b[38;2;214;121;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;105;67;2m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;163;95;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;209;122;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;85;52;2m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;14;23;27m▀\x1b[0m',
    '        \x1b[38;2;0;0;0m▄\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;95;66;12m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;245;139;0m▀\x1b[0m\x1b[38;2;51;82;97m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;4;10;12m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;158;92;0m▀\x1b[0m\x1b[38;2;163;98;0m\x1b[48;2;230;130;0m▀\x1b[0m\x1b[38;2;224;127;0m\x1b[48;2;230;130;0m▀\x1b[0m\x1b[38;2;230;130;0m\x1b[48;2;209;118;0m▀\x1b[0m\x1b[38;2;230;126;0m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;230;130;0m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;230;130;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;224;127;0m▀\x1b[0m\x1b[38;2;224;127;0m\x1b[48;2;81;55;6m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;17;26m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;56;87m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;1;3;4m▀\x1b[0m\x1b[38;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m▀\x1b[0m',
    '      \x1b[38;2;8;20;23m▄\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;103;63;4m▀\x1b[0m\x1b[38;2;147;95;11m\x1b[48;2;219;124;0m▀\x1b[0m\x1b[38;2;240;136;0m\x1b[48;2;112;65;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;219;121;0m▀\x1b[0m\x1b[38;2;122;71;0m\x1b[48;2;219;121;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;179;101;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;194;110;0m▀\x1b[0m\x1b[38;2;9;7;2m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;230;126;0m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;204;112;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;185;117;9m\x1b[48;2;0;61;92m▀\x1b[0m\x1b[38;2;37;95;74m\x1b[48;2;0;56;87m▀\x1b[0m\x1b[38;2;0;58;87m\x1b[48;2;0;61;92m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;4;5m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;31;46m▀\x1b[0m\x1b[38;2;0;56;87m\x1b[48;2;0;56;87m▀\x1b[0m\x1b[38;2;0;56;87m\x1b[48;2;0;24;36m▀\x1b[0m\x1b[38;2;0;38;56m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;7;16;18m▀\x1b[0m\x1b[38;2;14;27;32m▀\x1b[0m',
    '     \x1b[38;2;28;46;54m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;69;56;13m▀\x1b[0m\x1b[38;2;224;131;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;204;116;0m\x1b[48;2;224;123;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;189;107;0m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;224;127;0m\x1b[48;2;70;46;1m▀\x1b[0m\x1b[38;2;224;123;0m\x1b[48;2;180;114;8m▀\x1b[0m\x1b[38;2;219;121;0m\x1b[48;2;0;61;92m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;56;87m\x1b[48;2;0;60;92m▀\x1b[0m\x1b[38;2;0;61;92m\x1b[48;2;0;49;71m▀\x1b[0m\x1b[38;2;0;61;92m\x1b[48;2;0;59;87m▀\x1b[0m\x1b[38;2;0;61;92m\x1b[48;2;0;66;97m▀\x1b[0m\x1b[38;2;0;65;97m\x1b[48;2;0;61;92m▀\x1b[0m\x1b[38;2;0;61;92m\x1b[48;2;0;44;66m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m',
    '     \x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;50;77m▀\x1b[0m\x1b[38;2;2;34;44m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;152;108;22m\x1b[48;2;0;17;26m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;7;10m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;61;92m\x1b[48;2;0;58;87m▀\x1b[0m\x1b[38;2;0;58;87m\x1b[48;2;0;56;87m▀\x1b[0m\x1b[38;2;0;58;87m\x1b[48;2;0;53;82m▀\x1b[0m\x1b[38;2;0;31;46m\x1b[48;2;0;51;77m▀\x1b[0m\x1b[38;2;0;60;92m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;61;92m\x1b[48;2;0;4;5m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;11;15m▀\x1b[0m\x1b[38;2;0;70;102m\x1b[48;2;0;70;102m▀\x1b[0m\x1b[38;2;0;66;97m\x1b[48;2;0;36;51m▀\x1b[0m\x1b[38;2;0;18;26m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m',
    '     \x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;4;5m▀\x1b[0m\x1b[38;2;0;15;20m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;58;87m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;61;92m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;17;26m\x1b[48;2;0;61;92m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;61;92m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;15;20m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;50;77m▀\x1b[0m\x1b[38;2;0;56;87m\x1b[48;2;0;53;82m▀\x1b[0m\x1b[38;2;0;56;87m\x1b[48;2;0;35;51m▀\x1b[0m\x1b[38;2;0;56;87m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;8;10m▀\x1b[0m\x1b[38;2;0;71;102m\x1b[48;2;0;75;107m▀\x1b[0m\x1b[38;2;0;71;102m\x1b[48;2;0;33;46m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;13;21;28m▀\x1b[0m\x1b[38;2;5;12;15m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;1;3;4m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;7;15;19m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;15;21;31m▄\x1b[0m',
    '     \x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;70;102m\x1b[48;2;0;75;107m▀\x1b[0m\x1b[38;2;0;71;102m\x1b[48;2;0;75;107m▀\x1b[0m\x1b[38;2;0;79;112m\x1b[48;2;0;75;107m▀\x1b[0m\x1b[38;2;0;64;87m\x1b[48;2;0;71;102m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;11;15m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;65;97m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;42;61m\x1b[48;2;0;66;97m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;49;71m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;39;56m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;44;61m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;80;112m\x1b[48;2;0;80;112m▀\x1b[0m\x1b[38;2;0;26;36m\x1b[48;2;0;79;112m▀\x1b[0m\x1b[38;2;12;29;34m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;14;20;27m▄\x1b[0m \x1b[38;2;14;20;27m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;20;36;46m▄\x1b[0m',
    '     \x1b[38;2;4;13;16m▀\x1b[0m\x1b[38;2;0;54;77m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;75;107m\x1b[48;2;0;84;117m▀\x1b[0m\x1b[38;2;0;18;26m\x1b[48;2;0;67;92m▀\x1b[0m\x1b[38;2;0;70;102m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;70;102m\x1b[48;2;0;61;87m▀\x1b[0m\x1b[38;2;0;71;102m\x1b[48;2;0;70;102m▀\x1b[0m\x1b[38;2;0;70;102m\x1b[48;2;0;66;97m▀\x1b[0m\x1b[38;2;0;70;102m\x1b[48;2;0;66;97m▀\x1b[0m\x1b[38;2;0;66;97m\x1b[48;2;0;70;102m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;10;23;26m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;43;69;85m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;84;117m\x1b[48;2;0;4;5m▀\x1b[0m\x1b[38;2;0;84;117m\x1b[48;2;0;86;117m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;79;107m▀\x1b[0m\x1b[38;2;0;0;0m▄\x1b[0m  \x1b[38;2;0;0;0m\x1b[48;2;8;13;17m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;21;34;40m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;21;34;40m\x1b[48;2;0;16;20m▀\x1b[0m\x1b[38;2;16;30;27m\x1b[48;2;0;0;0m▀\x1b[0m',
    '      \x1b[38;2;18;28;33m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;10;16;21m▀\x1b[0m\x1b[38;2;0;88;122m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;82;112m\x1b[48;2;0;42;56m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;86;117m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;94;128m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;79;107m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;46;61m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;14;31;37m\x1b[48;2;14;27;32m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;24;40;48m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;26;39;50m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;8;20;22m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;7;8;13m▀\x1b[0m\x1b[38;2;0;0;0m▀\x1b[0m\x1b[38;2;8;24;27m▀\x1b[0m\x1b[38;2;17;38;44m▀\x1b[0m\x1b[38;2;0;27;36m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;86;117m\x1b[48;2;0;65;87m▀\x1b[0m\x1b[38;2;0;38;51m\x1b[48;2;0;90;122m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;94;128m▀\x1b[0m\x1b[38;2;21;43;50m\x1b[48;2;0;94;128m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;15;20m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;79;92;150m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;16;31;35m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;30;50;62m\x1b[48;2;0;25;36m▀\x1b[0m\x1b[38;2;17;29;34m▄\x1b[0m',
    '         \x1b[38;2;13;21;28m▀\x1b[0m\x1b[38;2;0;0;0m▀\x1b[0m\x1b[38;2;0;26;36m\x1b[48;2;17;35;39m▀\x1b[0m\x1b[38;2;0;19;26m\x1b[48;2;0;8;10m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;71;125;138m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;25;43;52m▀\x1b[0m\x1b[38;2;26;104;124m\x1b[48;2;14;23;27m▀\x1b[0m\x1b[38;2;130;168;186m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;7;13;12m\x1b[48;2;14;23;27m▀\x1b[0m     \x1b[38;2;0;0;0m▀\x1b[0m\x1b[38;2;0;20;26m\x1b[48;2;16;23;30m▀\x1b[0m\x1b[38;2;0;57;77m\x1b[48;2;10;17;21m▀\x1b[0m\x1b[38;2;0;46;61m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;130;182;192m▀\x1b[0m\x1b[38;2;0;0;0m\x1b[48;2;0;0;0m▀\x1b[0m\x1b[38;2;20;116;148m\x1b[48;2;12;19;24m▀\x1b[0m\x1b[38;2;7;35;44m\x1b[48;2;10;23;25m▀\x1b[0m\x1b[38;2;2;3;3m▀\x1b[0m\x1b[38;2;0;0;0m▀\x1b[0m\x1b[38;2;14;23;27m▀\x1b[0m\x1b[38;2;0;0;0m▀\x1b[0m',
    '            \x1b[38;2;12;25;29m▀\x1b[0m\x1b[38;2;14;33;37m▀\x1b[0m\x1b[38;2;0;0;0m▀\x1b[0m             \x1b[38;2;18;33;38m▀\x1b[0m\x1b[38;2;18;33;38m▀\x1b[0m',
    '',
    '',
    '',
]

# ── logo animation ────────────────────────────────────────────────────────────

_HUE_STEP       = 0.02    # hue advance per 50 ms tick → full cycle ≈ 17 s
_HUE_DELAY      = 15.0      # seconds of idle before animation begins
_SAT_THRESHOLD  = 0.05     # pixels below this saturation are treated as grey and not shifted

# Tokenise a logo line into ANSI escape codes and plain-text runs.
_TOKEN_RE = re.compile(r'(\x1b\[[^m]*m)|([^\x1b]+)')


def _parse_logo_lines(lines):
    """Parse _LOGO_LINES into a list of per-line segment lists.

    Each segment is (text, fg_rgb_or_None, bg_rgb_or_None).
    """
    result = []
    for line in lines:
        segs = []
        cur_fg = None
        cur_bg = None
        for m in _TOKEN_RE.finditer(line):
            esc, text = m.group(1), m.group(2)
            if esc:
                code  = esc[2:-1]            # strip \x1b[ … m
                parts = code.split(';')
                if parts[0] in ('0', ''):
                    cur_fg = None
                    cur_bg = None
                elif len(parts) == 5 and parts[1] == '2':
                    rgb = (int(parts[2]), int(parts[3]), int(parts[4]))
                    if parts[0] == '38':
                        cur_fg = rgb
                    elif parts[0] == '48':
                        cur_bg = rgb
            else:
                segs.append((text, cur_fg, cur_bg))
        result.append(segs)
    return result


_LOGO_PARSED = _parse_logo_lines(_LOGO_LINES)


def _shift_rgb(rgb, delta_hue):
    """Return rgb with hue rotated by delta_hue (0–1).  Near-grey pixels are unchanged."""
    if rgb is None:
        return None
    r, g, b = rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < _SAT_THRESHOLD:
        return rgb
    h = (h + delta_hue) % 1.0
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return (round(r2 * 255), round(g2 * 255), round(b2 * 255))


def _render_logo_line(segs, hue_offset):
    """Re-encode one parsed logo line with the given hue shift applied."""
    parts = []
    for text, fg, bg in segs:
        sfg = _shift_rgb(fg, hue_offset)
        sbg = _shift_rgb(bg, hue_offset)
        if sfg is not None:
            parts.append(f'\x1b[38;2;{sfg[0]};{sfg[1]};{sfg[2]}m')
        if sbg is not None:
            parts.append(f'\x1b[48;2;{sbg[0]};{sbg[1]};{sbg[2]}m')
        parts.append(text)
        if sfg is not None or sbg is not None:
            parts.append('\x1b[0m')
    return ''.join(parts)


# ── data helpers ─────────────────────────────────────────────────────────────

def load_global_config():
    if not os.path.isfile(GLOBAL_CONFIG_PATH):
        return dict(_DEFAULTS)
    try:
        with open(GLOBAL_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
        cfg = dict(_DEFAULTS)
        for k in _DEFAULTS:
            if k in data:
                cfg[k] = data[k]
        return cfg
    except Exception:
        return dict(_DEFAULTS)


def save_global_config(cfg):
    os.makedirs(os.path.dirname(GLOBAL_CONFIG_PATH), exist_ok=True)
    with open(GLOBAL_CONFIG_PATH, "w") as f:
        yaml.dump({k: cfg[k] for k in _DEFAULTS}, f, default_flow_style=False)


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



# "DendROS" title written below the logo art, in the bottom blank rows.
# "Dend" → frog's teal blue, "ROS" → frog's orange-yellow.  Both shift with the animation.
_TITLE_VISIBLE = 'D e n d   R O S'              # 15 visible chars
_TITLE_PAD     = (_LOGO_W - len(_TITLE_VISIBLE)) // 2   # = 13
_TITLE_BLUE    = (0, 75, 107)
_TITLE_ORANGE  = (224, 127, 0)


def _make_title_line(hue_offset):
    """Build the colored DendROS title string with hue-shifted colors."""
    b = _shift_rgb(_TITLE_BLUE,   hue_offset)
    o = _shift_rgb(_TITLE_ORANGE, hue_offset)
    return (
        ' ' * _TITLE_PAD
        + f'\x1b[1m\x1b[38;2;{b[0]};{b[1]};{b[2]}mD e n d\x1b[0m'
        + '   '
        + f'\x1b[1m\x1b[38;2;{o[0]};{o[1]};{o[2]}mR O S\x1b[0m'
    )


def _draw_logo_ansi(start_row, hue_offset=0.0):
    """Write the logo and DendROS title to stdout using raw 24-bit ANSI escape codes.

    Called after scr.refresh() each frame. Curses never writes to this region,
    so refresh() never clears it — the art persists without flicker.
    """
    out = []
    for i, segs in enumerate(_LOGO_PARSED):
        out.append(f'\033[{start_row + i + 1};1H{_render_logo_line(segs, hue_offset)}')
    title_row = start_row + _LOGO_ROWS - 1
    out.append(f'\033[{title_row};1H{_make_title_line(hue_offset)}')
    sys.stdout.write(''.join(out))
    sys.stdout.flush()


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
    scr.timeout(50)      # non-blocking: getch() returns -1 after 50 ms → ~20 fps animation

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
        fc = _LOGO_W + 2 if use_logo else 0   # field column offset

        # ── header ────────────────────────────────────────────────────────────
        tag   = "  [unsaved]" if dirty else ""
        brand = "  DendROS Config"
        path  = f"  {GLOBAL_CONFIG_PATH}"
        gap   = max(0, w - len(brand) - len(path) - len(tag))
        _put(scr, 0, 0,
             (brand + path + " " * gap + tag)[:w],
             curses.color_pair(_CP_HEADER) | curses.A_BOLD)

        # ── vertical divider (drawn by curses so it always renders) ───────────
        if use_logo:
            _draw_vline(scr, _LOGO_W, start_row=1, end_row=1 + _LOGO_ROWS + 1)

        # ── fields ────────────────────────────────────────────────────────────
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

        # ── description section ───────────────────────────────────────────────
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

        # ── status ────────────────────────────────────────────────────────────
        st_row = desc_end_row + 1
        if status[0]:
            _put(scr, st_row, fc + 2, status[0],
                 curses.color_pair(status[1]) | curses.A_BOLD)

        # ── footer ────────────────────────────────────────────────────────────
        hints = "  ↑↓ navigate   Space/→ cycle   e edit text   s save   q quit"
        _put(scr, h - 1, 0, hints[:w - 1].ljust(w - 1), curses.A_REVERSE | curses.A_DIM)

        # ── flush curses, then paint logo on top ──────────────────────────────
        scr.refresh()
        if use_logo:
            _draw_logo_ansi(start_row=1, hue_offset=hue_offset)

        # ── input ─────────────────────────────────────────────────────────────
        key = scr.getch()
        if key == -1:
            # Timeout tick — advance hue only after the idle delay has passed
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
            status = (f"Saved → {GLOBAL_CONFIG_PATH}", _CP_OK)

        elif key == curses.KEY_RESIZE:
            pass  # re-renders on next loop iteration

        elif key in (ord('q'), 27):
            if dirty:
                _put(scr, h - 4, fc + 2,
                     "Save before quitting? [y/N] ",
                     curses.color_pair(_CP_WARN) | curses.A_BOLD)
                scr.refresh()
                scr.timeout(-1)          # block until user actually responds
                confirm = scr.getch()
                scr.timeout(50)          # restore animation timeout
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
