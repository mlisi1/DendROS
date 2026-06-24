# Reference

## Environment variables

| Variable | Effect |
|---|---|
| `DENDROS_DEBUG=1` | Print config summary, color map, and group list to stderr on startup |
| `DENDROS_DISABLE=1` | Bypass DendROS entirely; call the real `ros2` binary directly |

```bash
# Confirm DendROS found your config and matched your node names
DENDROS_DEBUG=1 ros2 launch my_pkg my_launch.py

# Disable for a single invocation (env prefix, not persistent)
DENDROS_DISABLE=1 ros2 launch my_pkg my_launch.py

# Toggle for the entire shell session
dendros disable    # sets DENDROS_DISABLE=1 in the current shell
dendros enable     # unsets DENDROS_DISABLE
```

!!! note
    `DENDROS_DEBUG=1` always overrides the `debug` setting in `defaults.yaml`.

---

## dendROS.yaml — group keys

| Key | Required | Type | Description |
|---|---|---|---|
| `color` | yes | string | Color for this group. See [Colors](colors.md). |
| `label` | no | string | Short badge text shown as `[LOC]`. `""` = no badge. |
| `nodes` | yes | list | Node name patterns to match (supports `fnmatch` wildcards). |
| `show_tag` | no | bool | `false` suppresses the badge for this group only. |
| `color_mode` | no | string | `tag_only` or `full_line`. Overrides the package/global setting for this group. |
| `tag_style` | no | string | `normal` or `inverted`. Overrides badge style for this group. |
| `highlight` / `highlights` | no | list | Keyword entries to highlight within this group's output lines. See [Keyword highlighting](configuration.md#keyword-highlighting). |

---

## dendROS.yaml — defaults keys

| Key | Default | Type | Description |
|---|---|---|---|
| `color_mode` | `tag_only` | string | `tag_only` or `full_line`. |
| `show_group_tag` | `true` | bool | Show badges in `ros2 launch` / `ros2 run` output for all groups in this package. |
| `tag_position` | `after` | string | `after` or `before` — badge position relative to `[node-N]`. |
| `tag_style` | `normal` | string | `normal` or `inverted` — badge appearance. |
| `unmatched_color` | `null` | string\|null | Color for nodes not in any group. |
| `unmatched_tag` | `null` | string\|null | Badge for unmatched nodes. Only shown when `unmatched_color` is set. |
| `dim_unmatched` | `false` | bool | Dim unmatched nodes. Only when `unmatched_color: null`. |
| `colorize_launch_msgs` | `true` | bool | Colorize `[INFO] [node-N]: …` lifecycle lines. |
| `highlight` / `highlights` | `[]` | list | Keyword entries applied to all matched nodes in this package. See [Keyword highlighting](configuration.md#keyword-highlighting). |

---

## Global config — all keys

Stored in `~/.config/dendROS/defaults.yaml`, managed via `dendros config`:

| Key | Default | Description |
|---|---|---|
| `color_mode` | `tag_only` | Global default output mode. |
| `show_tag_launch` | `true` | Show badges in `ros2 launch` / `ros2 run` output globally. |
| `show_tag_cli` | `true` | Show badges in `ros2 node list`, `node info`, `service list`, `action list` globally. |
| `tag_position` | `after` | Badge position relative to `[node-N]` in launch/run output. |
| `tag_style` | `normal` | `normal` or `inverted` — badge appearance globally. |
| `unmatched_color` | `null` | Global fallback color for unmatched nodes. |
| `unmatched_tag` | `null` | Global badge for unmatched nodes. |
| `dim_unmatched` | `false` | Dim unmatched nodes globally. |
| `show_default_services` | `true` | When `false`, hide standard ROS 2 system services from `ros2 service list` output. |
| `debug` | `false` | Print debug output on startup. |
| `config_merge` | `true` | Merge configs from included packages. |
| `colorize_launch_msgs` | `true` | Colorize lifecycle lines globally. |
| `crash_alert` | `true` | Print an inline banner when a node dies unexpectedly. |
| `crash_alert_color` | `node` | `node` = use group color; `red` = always bold red. |
| `crash_alert_interval` | `30` | Seconds between periodic banner reprints. `0` = only on new crashes. |
| `traceback_color` | `fancy` | `fancy` = bold red header + dim red frames; `red` = all bold red; `off` = passthrough. |
| `init_modify_build` | `true` | `dendros init`: patch build files. |
| `init_on_existing` | `abort` | `dendros init`: `abort`, `merge`, or `overwrite`. |
| `init_color` | `palette` | `dendros init`: `palette` or `null`. |
| `init_color_bold` | `false` | `dendros init`: prefix palette colors with `bold`. |
| `init_label` | `false` | `dendros init`: auto-generate labels. |

---

## ros2 — intercepted subcommands

The `ros2()` shell wrapper intercepts specific subcommands; everything else calls the real `ros2` binary directly:

| Subcommand | Behavior |
|---|---|
| `ros2 launch …` | Output piped through the DendROS colorizer. |
| `ros2 run …` | Output piped through the DendROS colorizer. |
| `ros2 node list` | Output piped through `dendros_node_list.py` — nodes colored by group. See [ros2 node list](node-list.md). |
| `ros2 node info …` | Output piped through `dendros_node_info.py` — node name, sections, and entries colorized by group. See [ros2 node info](node-info.md). |
| `ros2 service list` | Output piped through `dendros_service_list.py` — services colored by owning node; default system services dimmed. See [ros2 service list](service-list.md). |
| `ros2 action list` | Output piped through `dendros_action_list.py` — actions colored by owning node. See [ros2 action list](action-list.md). |
| Everything else | Passed directly to the real `ros2` binary, untouched. |

---

## dendros — subcommands

| Subcommand | Description |
|---|---|
| `dendros config` | Open the interactive global-settings TUI. |
| `dendros init` | Scaffold `config/dendROS.yaml` from launch files. See flags below. |
| `dendros disable` | Set `DENDROS_DISABLE=1` in the current shell — colorization off until re-enabled. |
| `dendros enable` | Unset `DENDROS_DISABLE` — restore colorization in the current shell. |

Tab completion is available for all subcommands and `dendros init` flags after sourcing `dendROS.sh`.

---

## dendros init — CLI flags

| Flag | Alias | Description |
|---|---|---|
| `--recursive` | `-r` | Follow launch file includes into external packages (BFS, cycle-safe). |
| `--labels` | `-l` | Auto-generate short uppercase labels from package names. |

---

## Node matching rules

Matching is performed in this order; first match wins:

1. **Exact full-path** — `/ns/talker` matches only nodes at that exact path
2. **Exact basename** — `talker` matches `[talker-1]` under any namespace
3. **Wildcard full-path** — `*/amcl` matches `/robot/amcl`, `/ns/amcl`, …
4. **Wildcard basename** — `nav2_*` matches `nav2_controller`, `nav2_planner`, …

`fnmatch` syntax: `*` (any chars), `?` (one char), `[seq]` (character class).
The numeric instance suffix (`-N`) is stripped before matching.
