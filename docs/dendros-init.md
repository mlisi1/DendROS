# dendros init

`dendros init` scaffolds a `config/dendROS.yaml` from a package's launch files automatically.

---

## Basic usage

Run from the root of a ROS 2 package:

```bash
cd ~/ros2_ws/src/my_bringup
dendros init
```

DendROS scans every `.py` and `.xml` file in `launch/`, extracts all `Node()` / `ComposableNode()` / `<node/>` calls, groups them by source package, and writes `config/dendROS.yaml`. It also patches `CMakeLists.txt` / `setup.py` / `setup.cfg` so the config is installed with the package.

### Example output

```
[dendROS] package: my_bringup  root: /ws/src/my_bringup
[dendROS] scanning launch files…
[dendROS]   main.launch.py: 2 node(s)
[dendROS] found 2 node(s) in 1 group(s)
[dendROS] created /ws/src/my_bringup/config/dendROS.yaml
```

### Generated config

```yaml
groups:
  my_bringup:
    color: blue
    label: ""
    nodes:
      - my_node
      - another_node

defaults:
  color_mode: tag_only
  show_group_tag: true
  unmatched_color: null
```

`label: ""` is written for every group as a placeholder — fill it in manually.

---

## Recursive mode

Follow `IncludeLaunchDescription` / `<include>` references into external packages:

```bash
dendros init --recursive   # or: dendros init -r
```

Packages are found via (in order):

1. `ros2 pkg prefix` → installed packages
2. `AMENT_PREFIX_PATH` entries
3. Sibling directory in the same workspace `src/` folder (for packages not yet installed)

Packages that cannot be located produce a warning but do not abort the scan.

### Example output

```
[dendROS] package: my_bringup  root: /ws/src/my_bringup
[dendROS] scanning (recursive) launch files…
[dendROS]   main.launch.py: 2 node(s)
[dendROS] recursive: found references to: nav2_bringup, slam_toolbox, xsens_mti_ros2_driver
[dendROS]   nav2_bringup/bringup_launch.py [install]: 8 node(s)
[dendROS]   slam_toolbox/online_async_launch.py [source]: 1 node(s)
[dendROS]   xsens_mti_ros2_driver: not found (not in install tree or source siblings)
[dendROS] found 11 node(s) in 3 group(s)
[dendROS] created /ws/src/my_bringup/config/dendROS.yaml
```

---

## Auto-generate labels

Pass `--labels` (or `-l`) to auto-generate short uppercase labels from package names:

```bash
dendros init --labels
dendros init -r -l        # recursive + labels
```

| Package name | Generated label |
|---|---|
| `slam_toolbox` | `ST` |
| `nav2_bringup` | `NB` |
| `robot_state_publisher` | `RSP` |
| `my_pkg` | `MY` |

Without `--labels`, `label: ""` is written for every group so you can fill it in manually.

---

## Behavior options

All options are configurable via `dendros config` → Init settings:

| Setting | Values | Effect |
|---|---|---|
| `init_on_existing` | `abort` *(default)* / `merge` / `overwrite` | What to do if `config/dendROS.yaml` already exists. `merge` adds new nodes only. |
| `init_modify_build` | `on` *(default)* / `off` | Auto-patch `CMakeLists.txt` / `setup.py` / `setup.cfg` to install the config. |
| `init_color` | `palette` *(default)* / `null` | Assign cycling colors to groups, or leave all as `color: null` for manual editing. |
| `init_color_bold` | `off` *(default)* / `on` | Prefix every palette color with `bold` (e.g. `bold blue`). |
| `init_label` | `off` *(default)* / `on` | Auto-generate labels (same as `--labels`). `off` writes `label: ""`. |

### Using merge mode

If a `dendROS.yaml` already exists, `merge` adds nodes found in launch files that aren't already listed, without touching existing entries:

```bash
# Set merge mode permanently:
dendros config   # → Init: on existing → merge

# Or override once by editing defaults.yaml directly:
# ~/.config/dendROS/defaults.yaml: init_on_existing: merge
```
