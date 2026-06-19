# dendros config

`dendros config` opens an interactive TUI for managing global defaults. Settings are written to `~/.config/dendROS/defaults.yaml` and apply across all packages as a baseline. Per-package `dendROS.yaml` `defaults:` sections override them.

---

## Opening the TUI

```bash
dendros config
```

The TUI shows a colorized frog logo on the left when the terminal is at least 96 columns wide.

---

## Interface

```
  DendROS Config  ~/.config/dendROS/defaults.yaml

   ► Color mode             [tag_only]  full_line
     Show group tag         [on]  off
     Tag position           [after]  before
     Unmatched color        null
     Debug mode             [off]  on
     Config merge           [on]  off
     Colorize launch msgs   [on]  off
     Unmatched tag          null
     Dim unmatched          [off]  on
     Init: modify build     [on]  off
     Init: on existing      [abort]  merge  overwrite
     Init: color            [palette]  null
     Init: bold colors      [off]  on
     Init: auto label       [off]  on

  ──────────────────────────────────────────────────
  tag_only — color [node-N] prefix and [TAG] badge only;
  preserves ROS 2 severity colors (WARN=yellow, ERROR=red)

  ↑↓ navigate   Space/→ cycle   e edit text   s save   q quit
```

### Keys

| Key | Action |
|---|---|
| `↑` / `k` | Previous field |
| `↓` / `j` | Next field |
| `→` / `Space` / `Enter` | Cycle option forward |
| `←` | Cycle option backward |
| `e` | Open inline text editor for the current field |
| `s` | Save to `~/.config/dendROS/defaults.yaml` |
| `q` / `Esc` | Quit (prompts if there are unsaved changes) |

---

## Settings reference

### Output

| Setting | Values | Description |
|---|---|---|
| **Color mode** | `tag_only` / `full_line` | `tag_only` colors prefix + badge only, preserving ROS 2 severity colors. `full_line` colors the entire line. |
| **Show group tag** | `on` / `off` | Show `[TAG]` badges globally. Can be overridden per-group with `show_tag: false`. |
| **Tag position** | `after` / `before` | Place the badge after (`[node-N] [TAG] …`) or before (`[TAG] [node-N] …`) the node prefix. |
| **Colorize launch msgs** | `on` / `off` | When off, `[INFO] [node-N]: process started …` lifecycle lines pass through unchanged. Node output is still colorized. |

### Unmatched nodes

| Setting | Values | Description |
|---|---|---|
| **Unmatched color** | color / `null` | Color applied to nodes not in any group. `null` = pass through unchanged. |
| **Unmatched tag** | string / `null` | Badge shown next to unmatched nodes (e.g. `?` → `[?]`). Only shown when `unmatched_color` is set. |
| **Dim unmatched** | `on` / `off` | Apply ANSI dim to unmatched nodes. Only applies when `unmatched_color` is `null`. |

### Other

| Setting | Values | Description |
|---|---|---|
| **Debug mode** | `on` / `off` | Print config summary to stderr on startup. Equivalent to `DENDROS_DEBUG=1`. |
| **Config merge** | `on` / `off` | Parse launch files for referenced packages and merge their configs. |

### Init settings

These control the behavior of `dendros init`:

| Setting | Values | Description |
|---|---|---|
| **Init: modify build** | `on` / `off` | Auto-patch `CMakeLists.txt` / `setup.py` / `setup.cfg`. |
| **Init: on existing** | `abort` / `merge` / `overwrite` | What to do if `config/dendROS.yaml` already exists. |
| **Init: color** | `palette` / `null` | Assign cycling colors to groups, or leave all as `color: null`. |
| **Init: bold colors** | `on` / `off` | Prefix every palette color with `bold`. |
| **Init: auto label** | `on` / `off` | Auto-generate short labels from package names (same as `--labels` flag). |

---

## Config file

Settings are stored in plain YAML:

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
init_modify_build: true
init_on_existing: abort
init_color: palette
init_color_bold: false
init_label: false
```

You can edit this file directly — `dendros config` reads and writes it on every save.
