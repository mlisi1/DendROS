# dendros config

`dendros config` opens a full-screen interactive TUI for managing global defaults.

```bash
dendros config
```

Settings are written to `~/.config/dendROS/defaults.yaml` and apply across all packages as a baseline. Per-package `dendROS.yaml` `defaults:` sections override them.

---

## Interface


<div class="term">
  <div class="term-bar">
    <div class="term-dots">
      <div class="term-dot term-dot-red"></div>
      <div class="term-dot term-dot-yellow"></div>
      <div class="term-dot term-dot-green"></div>
    </div>
    <div class="term-title">dendros config</div>
  </div>
  <div class="term-body-image">
  <p align="center">
<img src="../assets/images/screenshots/dendros_config.png" width="900" alt="dendros config"/>
</p>
</div>
</div>

---

## Keyboard reference

| Key | Action |
|---|---|
| ++up++ / ++k++ | Move to previous field |
| ++down++ / ++j++ | Move to next field |
| ++right++ / ++space++ / ++enter++ | Cycle option forward |
| ++left++ | Cycle option backward |
| ++e++ | Open inline text editor for the current field |
| ++s++ | Save to `~/.config/dendROS/defaults.yaml` |
| ++q++ / ++escape++ | Quit (prompts if there are unsaved changes) |

---

## Settings reference

### Output (launch / run)

| Setting | Values | Description |
|---|---|---|
| **Color mode** | `tag_only` / `full_line` | `tag_only` colors prefix + badge, preserving severity colors. `full_line` colors the entire line. |
| **Show tag (launch/run)** | `on` / `off` | Show `[TAG]` badges in `ros2 launch` and `ros2 run` output. Overridable per-group with `show_tag: false`. |
| **Tag position** | `after` / `before` | Badge position: `after` → `[node-N] [TAG] …` · `before` → `[TAG] [node-N] …`. |
| **Tag style** | `normal` / `inverted` | `normal` = colored text on default background. `inverted` = colored background with empty letters (like crash alert banners). Overridable per-group with `tag_style:`. |
| **Colorize launch msgs** | `on` / `off` | When off, `[INFO] [node-N]: process started …` lines pass through unchanged. |

### CLI commands

| Setting | Values | Description |
|---|---|---|
| **Show tag (CLI)** | `on` / `off` | Show `[TAG]` badges in `ros2 node list`, `ros2 node info`, `ros2 service list`, and `ros2 action list`. |
| **Show default services** | `on` / `off` | When off, standard ROS 2 system services (`set_parameters`, `get_parameters`, `get_loggers`, …) are hidden from `ros2 service list` output entirely. When on, they appear dimmed. |

### Unmatched nodes

| Setting | Values | Description |
|---|---|---|
| **Unmatched color** | color / `null` | Color for nodes not in any group. `null` = pass through. |
| **Unmatched tag** | string / `null` | Badge for unmatched nodes (e.g. `?` → `[?]`). Requires `unmatched_color`. |
| **Dim unmatched** | `on` / `off` | Dim unmatched nodes. Only when `unmatched_color` is `null`. |

### System

| Setting | Values | Description |
|---|---|---|
| **Debug mode** | `on` / `off` | Print config summary to stderr on startup. Equivalent to `DENDROS_DEBUG=1`. |
| **Config merge** | `on` / `off` | Parse launch files for referenced packages and merge their configs. |

### Crash alert

| Setting | Values | Description |
|---|---|---|
| **Crash alert** | `on` / `off` | Print an inline banner when a node dies unexpectedly. See [Crash Alert](crash-alert.md). |
| **Crash alert color** | `node` / `red` | `node` uses the group color; `red` always uses bold red. |
| **Crash alert interval** | integer (seconds) | Seconds between periodic banner reprints. `0` = only on new crash events. |

### Traceback

| Setting | Values | Description |
|---|---|---|
| **Traceback color** | `fancy` / `red` / `off` | `fancy` = bold red header + dim red frames; `red` = all bold red; `off` = passthrough. See [Traceback Highlighting](traceback-highlighting.md). |

### Parameter change alert

| Setting | Values | Description |
|---|---|---|
| **Param change alert** | `on` / `off` | Print an inline notification whenever a node's parameter changes at runtime. See [Parameter Change Alert](param-change-alert.md). |
| **Param alert scope** | `tracked` / `all` | `tracked` = only nodes with a config group; `all` = entire ROS graph. |
| **Param alert style** | `inline` / `inverted` | `inline` = compact colored line; `inverted` = full white-background strip, harder to miss in busy logs. |

### Init defaults

| Setting | Values | Description |
|---|---|---|
| **Init: modify build** | `on` / `off` | Auto-patch build files when running `dendros init`. |
| **Init: on existing** | `abort` / `merge` / `overwrite` | What to do when a config already exists. |
| **Init: color** | `palette` / `null` | Assign cycling palette colors or leave as `null`. |
| **Init: bold colors** | `on` / `off` | Prefix every palette color with `bold`. |
| **Init: auto label** | `on` / `off` | Auto-generate labels (same as `--labels` flag). |

---

## Config file

```yaml
# ~/.config/dendROS/defaults.yaml
color_mode: tag_only
show_tag_launch: true
show_tag_cli: true
tag_position: after
tag_style: normal
unmatched_color: null
unmatched_tag: null
dim_unmatched: false
show_default_services: true
debug: false
config_merge: true
colorize_launch_msgs: true
crash_alert: true
crash_alert_color: node
crash_alert_interval: 30
traceback_color: fancy
param_change_alert: true
param_change_alert_scope: tracked
param_change_alert_style: inline
init_modify_build: true
init_on_existing: abort
init_color: palette
init_color_bold: false
init_label: false
```
