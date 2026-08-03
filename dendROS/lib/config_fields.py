"""Data layer for dendros_config.py's tabbed settings TUI — no curses dependency.

Field/_FIELDS/_TAB_ORDER declare every setting and which tab it belongs to; _DESCS holds
the help text shown for the selected field. dendros_config.py imports this module and adds
no data of its own beyond it.
"""

from typing import List, NamedTuple, Optional


class Field(NamedTuple):
    """One setting row. `group` must be a tab_id declared in _TAB_ORDER.

    Appended at the end (not inserted) so existing positional access
    (f[0], f[2], f[3]) keeps working — only exact-4-variable unpacking breaks.
    """
    key:   str
    label: str
    kind:  str                    # "cycle" | "text"
    opts:  Optional[List[object]]
    group: str


# (tab_id, display_label) — order here is the order tabs render left-to-right.
# This controls tab ORDER/LABEL only; the field→tab mapping lives solely in
# each Field.group below, so adding a setting later never touches this list
# unless it needs a brand-new category.
_TAB_ORDER = [
    ("output",      "Output"),
    ("cli",         "CLI"),
    ("unmatched",   "Unmatched"),
    ("system",      "System"),
    ("diagnostics", "Diagnostics"),
    ("param",       "Param Alerts"),
    ("init",        "Init"),
]

_FIELDS = [
    # ── Output (launch / run) ────────────────────────────────────────────────
    Field("color_mode",            "Color mode",              "cycle", ["tag_only", "full_line"],          "output"),
    Field("show_tag_launch",       "Show tag (launch/run)",   "cycle", [True, False],                       "output"),
    Field("tag_position",          "Tag position",             "cycle", ["after", "before"],                "output"),
    Field("tag_style",             "Tag style",                "cycle", ["normal", "inverted"],             "output"),
    Field("colorize_launch_msgs",  "Colorize launch msgs",     "cycle", [True, False],                       "output"),
    Field("show_timestamp",        "Show timestamp",           "cycle", [True, False],                       "output"),
    Field("show_logger_name",      "Show logger name",         "cycle", [True, False],                       "output"),
    Field("launch_mode",           "Launch mode",               "cycle", ["classic", "tui"],                 "output"),
    Field("tui_scrollback_lines",  "TUI scrollback lines",      "text",  None,                                "output"),
    Field("ignore_bold",           "Ignore bold",                "cycle", [False, True],                      "output"),

    # ── CLI commands ─────────────────────────────────────────────────────────
    Field("show_tag_cli",          "Show tag (CLI)",           "cycle", [True, False],                       "cli"),
    Field("show_default_services", "Show default services",   "cycle", [True, False],                       "cli"),
    Field("topic_sort",            "Topic list sort",          "cycle", ["default", "group"],               "cli"),

    # ── Unmatched nodes ──────────────────────────────────────────────────────
    Field("unmatched_color",       "Unmatched color",          "text",  None,                                "unmatched"),
    Field("unmatched_tag",         "Unmatched tag",             "text",  None,                                "unmatched"),
    Field("dim_unmatched",         "Dim unmatched",             "cycle", [False, True],                       "unmatched"),

    # ── System ───────────────────────────────────────────────────────────────
    Field("debug",                 "Debug mode",                "cycle", [False, True],                      "system"),
    Field("config_merge",          "Config merge",              "cycle", [True, False],                      "system"),

    # ── Diagnostics (crash alert + traceback) ────────────────────────────────
    Field("crash_alert",           "Crash alert",               "cycle", [False, True],                      "diagnostics"),
    Field("crash_alert_color",     "Alert color",                "cycle", ["node", "red"],                   "diagnostics"),
    Field("crash_alert_interval",  "Alert interval (s)",         "text",  None,                                "diagnostics"),
    Field("traceback_color",       "Traceback color",            "cycle", ["fancy", "red", "off"],           "diagnostics"),

    # ── Parameter change alert ───────────────────────────────────────────────
    Field("param_change_alert",       "Param change alert",     "cycle", [False, True],                      "param"),
    Field("param_change_alert_scope", "Param alert scope",       "cycle", ["tracked", "all"],                "param"),
    Field("param_change_alert_style", "Param alert style",       "cycle", ["inline", "inverted"],            "param"),

    # ── Init defaults ────────────────────────────────────────────────────────
    Field("init_modify_build",     "Init: modify build",        "cycle", [True, False],                      "init"),
    Field("init_on_existing",      "Init: on existing",          "cycle", ["abort", "merge", "overwrite"],  "init"),
    Field("init_color",            "Init: color",                "cycle", ["palette", "null"],               "init"),
    Field("init_color_bold",       "Init: bold colors",           "cycle", [False, True],                    "init"),
    Field("init_label",            "Init: auto label",            "cycle", [False, True],                    "init"),
]


def _fields_for_tab(tab_id):
    """Return the Field entries whose group == tab_id, in _FIELDS declaration order."""
    return [f for f in _FIELDS if f.group == tab_id]


_TAB_IDS = {tid for tid, _ in _TAB_ORDER}
assert not ({f.group for f in _FIELDS} - _TAB_IDS), (
    f"Field group(s) not declared in _TAB_ORDER: {({f.group for f in _FIELDS} - _TAB_IDS)}"
)
assert all(_fields_for_tab(tid) for tid, _ in _TAB_ORDER), "Every declared tab must have >=1 field"

_DESCS = {
    "color_mode": (
        "tag_only  — color [node-N] prefix and [TAG] badge only; preserves ROS 2"
        " severity colors (WARN=yellow, ERROR=red)",
        "full_line — strip embedded ANSI and color the entire line; cleaner but"
        " overrides severity colors",
    ),
    "show_tag_launch": (
        "on  — show colored [LOC] / [NAV] badges in ros2 launch / ros2 run output",
        "off — no badges in launch output; only the [node-N] prefix is colored",
    ),
    "show_tag_cli": (
        "on  — show colored [LOC] / [NAV] badges in ros2 node list / node info / service list / action list",
        "off — no badges in CLI commands; only the name itself is colored",
    ),
    "show_default_services": (
        "on  — include standard parameter/logger services in ros2 service list (shown dimmed)",
        "off — hide describe_parameters, get_parameters, set_parameters, get_loggers … from ros2 service list",
    ),
    "topic_sort": (
        "default — show topics in the order ros2 reports them (alphabetical by ROS 2)",
        "group   — system topics first, then topics grouped by publisher color group"
        " (groups in first-occurrence order, alphabetical within each group)",
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
    "show_timestamp": (
        "on  — show the [timestamp] bracket in node log lines"
        " ([node-N] [INFO] [timestamp] [logger]: msg)",
        "off — strip the timestamp bracket for a shorter log line",
    ),
    "show_logger_name": (
        "on  — show the [logger_name] bracket (the ROS graph name registered via"
        " get_logger(); can differ from the [node-N] launch process name)",
        "off — strip the logger name bracket for a shorter log line",
    ),
    "launch_mode": (
        "classic — pipe ros2 launch output straight to the terminal, colorized inline (default)",
        "tui     — open a full-screen scrollback view with a pinned crash/param alert banner."
        " ros2 launch only; automatically falls back to classic for ros2 run or non-interactive stdout",
    ),
    "tui_scrollback_lines": (
        "Number of lines kept in the TUI's scrollback buffer (PageUp/PageDown to navigate).",
        "Only used when launch_mode is tui. Default: 5000.",
    ),
    "ignore_bold": (
        "off — bold text renders as configured (default)",
        "on  — compatibility fix: some terminals brighten bold *foreground* text but never"
        " brighten backgrounds, so a group's bold color can look like two different shades"
        " between a node's regular text and its inverted [TAG] badge (or between classic-mode"
        " output and a CLI command's output). Enable this if colors look inconsistent in your"
        " terminal — strips the bold modifier everywhere colors are resolved, launch/run,"
        " the TUI, and all `ros2 node/service/action/param/topic` commands alike.",
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
    "param_change_alert": (
        "on  — print an inline notification in the launch terminal whenever a parameter changes at runtime",
        "off — parameter changes are silent; use ros2 param get to check values manually",
    ),
    "param_change_alert_scope": (
        "tracked — only notify for nodes that have a color group in a dendROS.yaml config",
        "all     — notify for every node on the ROS graph (includes nodes with no config entry)",
    ),
    "param_change_alert_style": (
        "inline   — compact single line: [dendROS] param  [TAG] /node  param_name → value",
        "inverted — reverse-video block with node color as background; harder to miss",
    ),
}
