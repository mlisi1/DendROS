# Reference

## Environment variables

| Variable | Effect |
|---|---|
| `DENDROS_DEBUG=1` | Print config summary, color map, and group list to stderr on startup |
| `DENDROS_DISABLE=1` | Bypass DendROS entirely; call the real `ros2` binary directly |

```bash
# Confirm DendROS found your config and matched your node names
DENDROS_DEBUG=1 ros2 launch my_pkg my_launch.py

# Temporarily disable without un-sourcing
DENDROS_DISABLE=1 ros2 launch my_pkg my_launch.py
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

---

## dendROS.yaml — defaults keys

| Key | Default | Type | Description |
|---|---|---|---|
| `color_mode` | `tag_only` | string | `tag_only` or `full_line`. |
| `show_group_tag` | `true` | bool | Show badges for all groups in this package. |
| `tag_position` | `after` | string | `after` or `before` — badge position relative to `[node-N]`. |
| `unmatched_color` | `null` | string\|null | Color for nodes not in any group. |
| `unmatched_tag` | `null` | string\|null | Badge for unmatched nodes. Only shown when `unmatched_color` is set. |
| `dim_unmatched` | `false` | bool | Dim unmatched nodes. Only when `unmatched_color: null`. |
| `colorize_launch_msgs` | `true` | bool | Colorize `[INFO] [node-N]: …` lifecycle lines. |

---

## Global config — all keys

Stored in `~/.config/dendROS/defaults.yaml`, managed via `dendros config`:

| Key | Default | Description |
|---|---|---|
| `color_mode` | `tag_only` | Global default output mode. |
| `show_group_tag` | `true` | Show badges globally. |
| `tag_position` | `after` | Badge position relative to `[node-N]`. |
| `unmatched_color` | `null` | Global fallback color for unmatched nodes. |
| `unmatched_tag` | `null` | Global badge for unmatched nodes. |
| `dim_unmatched` | `false` | Dim unmatched nodes globally. |
| `debug` | `false` | Print debug output on startup. |
| `config_merge` | `true` | Merge configs from included packages. |
| `colorize_launch_msgs` | `true` | Colorize lifecycle lines globally. |
| `init_modify_build` | `true` | `dendros init`: patch build files. |
| `init_on_existing` | `abort` | `dendros init`: `abort`, `merge`, or `overwrite`. |
| `init_color` | `palette` | `dendros init`: `palette` or `null`. |
| `init_color_bold` | `false` | `dendros init`: prefix palette colors with `bold`. |
| `init_label` | `false` | `dendros init`: auto-generate labels. |

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
