# dendros config

`dendros config` opens a full-screen interactive TUI for managing global defaults.

```bash
dendros config
```

Settings are written to `~/.config/dendROS/defaults.yaml` and apply across all packages as a baseline. Per-package `dendROS.yaml` `defaults:` sections override them.

---

## Interface


![dendros config TUI](assets/images/screenshots/dendros_config.png)


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

### Output

| Setting | Values | Description |
|---|---|---|
| **Color mode** | `tag_only` / `full_line` | `tag_only` colors prefix + badge, preserving severity colors. `full_line` colors the entire line. |
| **Show group tag** | `on` / `off` | Show `[TAG]` badges globally. Overridable per-group with `show_tag: false`. |
| **Tag position** | `after` / `before` | Badge position: `after` → `[node-N] [TAG] …` · `before` → `[TAG] [node-N] …`. |
| **Colorize launch msgs** | `on` / `off` | When off, `[INFO] [node-N]: process started …` lines pass through unchanged. |

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
show_group_tag: true
tag_position: after
unmatched_color: null
unmatched_tag: null
dim_unmatched: false
debug: false
config_merge: true
colorize_launch_msgs: true
crash_alert: false
crash_alert_color: node
crash_alert_interval: 30
traceback_color: fancy
init_modify_build: true
init_on_existing: abort
init_color: palette
init_color_bold: false
init_label: false
```
