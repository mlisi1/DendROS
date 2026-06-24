"""Shared global config: canonical path, defaults, load/save."""

import os

try:
    import yaml
except ImportError:
    yaml = None

# Monkeypatch-able override for tests. When None, get_global_config_path()
# re-expands ~ at call time (so setenv('HOME', ...) works in tests).
GLOBAL_CONFIG_PATH = None

DEFAULTS = {
    "color_mode":           "tag_only",
    "show_tag_launch":      True,
    "show_tag_cli":         True,
    "tag_position":         "before",
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
    "crash_alert":          True,
    "crash_alert_color":    "node",
    "crash_alert_interval": 30,
    "traceback_color":      "fancy",
    "tag_style":            "normal",
    "show_default_services": True,
}


def get_global_config_path():
    """Return the effective config path. Re-expands ~ each call unless GLOBAL_CONFIG_PATH is set."""
    return GLOBAL_CONFIG_PATH if GLOBAL_CONFIG_PATH is not None else os.path.expanduser("~/.config/dendROS/defaults.yaml")


def get_node_colors_path():
    """Return path to the shared node→color map written by the pipe and read by ros2 node list."""
    return os.path.join(os.path.dirname(get_global_config_path()), 'node_colors.yaml')


def load_global_config():
    """Load the global config file, filling missing keys from DEFAULTS."""
    path = get_global_config_path()
    if not os.path.isfile(path):
        return dict(DEFAULTS)
    if yaml is None:
        return dict(DEFAULTS)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        cfg = dict(DEFAULTS)
        for k in DEFAULTS:
            if k in data:
                cfg[k] = data[k]
        return cfg
    except Exception:
        return dict(DEFAULTS)


def save_global_config(cfg):
    """Write cfg to the global config file (only known keys)."""
    if yaml is None:
        return
    path = get_global_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump({k: cfg[k] for k in DEFAULTS}, f, default_flow_style=False)
