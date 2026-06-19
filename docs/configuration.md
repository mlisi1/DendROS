# Config File

Place `dendROS.yaml` inside your package's `config/` directory:

```
my_bringup/
└── config/
    └── dendROS.yaml
```

DendROS finds the file automatically using `ros2 pkg prefix` or by scanning `AMENT_PREFIX_PATH`. No path configuration needed.

---

## Structure

```yaml
groups:

  localization:
    color: "bold blue"
    label: "LOC"
    nodes:
      - slam_toolbox
      - "*/amcl"

  navigation:
    color: "bold green"
    label: "NAV"
    nodes:
      - nav2_*

  hardware:
    color: "#CC8800"
    show_tag: false
    color_mode: full_line
    nodes:
      - robot_state_publisher

defaults:
  color_mode: "tag_only"
  show_group_tag: true
  tag_position: "after"
  unmatched_color: null
  unmatched_tag: null
  dim_unmatched: false
  colorize_launch_msgs: true
```

---

## Groups

Each entry under `groups:` defines a set of nodes that share a color and optional badge label.

| Key | Required | Description |
|---|---|---|
| `color` | yes | Color for this group. See [Colors](colors.md). |
| `label` | no | Short badge shown as `[LOC]` after the node prefix. Empty string = no badge. |
| `nodes` | yes | List of node name patterns to match. |
| `show_tag` | no | Set `false` to suppress the badge for this group only (even when `show_group_tag: true` globally). |
| `color_mode` | no | Per-group override: `tag_only` or `full_line`. Overrides `defaults.color_mode` for these nodes only. |

---

## Node matching

Node names support `fnmatch` shell-glob patterns:

| Pattern | Matches |
|---|---|
| `slam_toolbox` | `[slam_toolbox-1]`, `[slam_toolbox-2]`, … |
| `/my_ns/talker` | only `[talker-1]` under `/my_ns` |
| `nav2_*` | `nav2_controller`, `nav2_planner`, `nav2_bt_navigator`, … |
| `*/amcl` | `/robot/amcl`, `/my_ns/amcl`, any namespaced `amcl` |
| `*controller*` | any node whose basename contains `controller` |
| `node_?` | `node_a`, `node_b`, … (one character wildcard) |

**Lookup order** — exact full-path → exact basename → wildcard full-path → wildcard basename. First match wins.

The numeric instance suffix is stripped before matching: `[talker-3]` is matched as `talker`.

---

## Defaults section

The `defaults:` section sets package-level defaults that override the global config for this package only.

| Key | Default | Description |
|---|---|---|
| `color_mode` | `tag_only` | `tag_only` or `full_line`. See [color_mode](#color_mode). |
| `show_group_tag` | `true` | Show `[TAG]` badges globally for this package. |
| `tag_position` | `after` | Badge position: `after` (`[node-N] [TAG] …`) or `before` (`[TAG] [node-N] …`). |
| `unmatched_color` | `null` | Color for nodes not in any group. `null` = pass through unchanged. |
| `unmatched_tag` | `null` | Badge for unmatched nodes (e.g. `"?"` → `[?]`). Only shown when `unmatched_color` is set. |
| `dim_unmatched` | `false` | Apply ANSI dim to unmatched nodes. Only applies when `unmatched_color: null`. |
| `colorize_launch_msgs` | `true` | Colorize `[INFO] [node-N]: process started …` lifecycle lines. `false` passes them through unchanged. |

---

## color_mode

Controls how much of each line is colored.

| Value | Behavior |
|---|---|
| `tag_only` *(default)* | Colors the `[node-N]` prefix and `[TAG]` badge only. ROS 2 severity colors (`[WARN]` = yellow, `[ERROR]` = red) are preserved. |
| `full_line` | Colors the entire line in the group's color. Severity colors are overridden. |

`color_mode` can be set at three levels, applied in this order (most specific wins):

1. **Per-group** — `color_mode: full_line` under a single group
2. **Per-package** — `color_mode:` in the `defaults:` section
3. **Global** — set via `dendros config`

---

## Full annotated example

See [`docs/dendROS.yaml.example`](https://github.com/mlisi1/DendROS/blob/main/docs/dendROS.yaml.example) in the repository for a complete annotated reference file.
