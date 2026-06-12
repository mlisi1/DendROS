<p align="center">
  <img src="res/logo.png" width="320" alt="DendROS logo"/>
</p>

<h1 align="center">DendROS</h1>
<p align="center">Colorized ROS 2 terminal output — assign colors to node groups without touching your launch files.</p>



```
[slam_toolbox-1]  [LOC]  [INFO] [...]: Serialization format: cdr
[bt_navigator-1]  [NAV]  [INFO] [...]: Creating BT navigator
[controller_server-1]  [NAV]  [WARN] [...]: Costmap is empty
[robot_state_publisher-1]  [HW]  [INFO] [...]: Robot description loaded
```

DendROS shadows the `ros2` command with a shell function. When you run `ros2 launch` or `ros2 run`, the output is piped through a colorizer that matches the `[node_name-N]` prefix ROS 2 always emits and applies your configured group colors. Every other `ros2` subcommand passes through unchanged.

The name comes from *Dendrobates* — the poison dart frog, famous for its vivid colors.



## Installation

### Host

```bash
git clone https://github.com/mlisi1/DendROS
cd DendROS
bash install.sh
source ~/.bashrc
```

### Docker

Add this snippet to your `Dockerfile` after your ROS 2 base setup:

```dockerfile
COPY dendROS/ /usr/local/dendROS/
RUN pip3 install --no-cache-dir pyyaml \
 && chmod +x /usr/local/dendROS/dendROS_pipe.py \
 && printf '\n# dendROS\nsource /usr/local/dendROS/dendROS.sh\n' >> /root/.bashrc
```

Or use the non-interactive installer:

```dockerfile
COPY . /tmp/dendROS/
RUN bash /tmp/dendROS/install.sh -y
```

Add to your `docker-compose.yml` service:

```yaml
services:
  my_robot:
    tty: true
    stdin_open: true
    environment:
      - RCUTILS_COLORIZED_OUTPUT=1
```

> `docker compose exec my_robot bash` sources `~/.bashrc` and activates the `ros2` function immediately. `docker compose up` log streaming has no TTY — `tty: true` is required for colors to render there.




## Configuration

Place a `dendROS.yaml` in your package's `config/` directory:

```
my_bringup/
└── config/
    └── dendROS.yaml
```

```yaml
groups:

  localization:
    color: "bold blue"
    label: "LOC"            # optional — shows [LOC] badge after the node prefix
    nodes:
      - slam_toolbox
      - "*/amcl"            # wildcard: matches /any_ns/amcl

  navigation:
    color: "bold green"
    label: "NAV"
    nodes:
      - nav2_*              # wildcard: covers all nav2_* nodes at once

  hardware:
    color: "#CC8800"        # hex truecolor
    nodes:
      - robot_state_publisher

defaults:
  color_mode: "tag_only"
  show_group_tag: true
  unmatched_color: null
```

See [`docs/dendROS.yaml.example`](docs/dendROS.yaml.example) for the full annotated reference.

### Wildcard node matching

Node names support `fnmatch` shell-glob patterns. This is handy for stacks like Nav2 that spawn many nodes with a common prefix:

| Pattern | Matches |
|---|---|
| `nav2_*` | `nav2_controller`, `nav2_planner`, `nav2_bt_navigator`, … |
| `*/amcl` | `/robot/amcl`, `/my_ns/amcl`, … |
| `*controller*` | any node whose basename contains "controller" |
| `node_?` | `node_a`, `node_b`, … (one character) |

Lookup order: exact full-path → exact basename → wildcard full-path → wildcard basename. The first match wins.

---
### Colors

The `color` field accepts three formats:

**Named colors** with optional modifiers:

| Modifier | Example | Effect |
|---|---|---|
| *(none)* | `"yellow"` | standard |
| `light` / `bright` | `"light yellow"` | bright variant |
| `dark` / `dim` | `"dark yellow"` | dim variant |
| `bold` | `"bold yellow"` | bold |
| combined | `"bold light cyan"` | bold + bright |

Available names: `black` `red` `green` `yellow` `blue` `magenta` `cyan` `white`

**Hex truecolor** (requires a modern terminal):

| Syntax | Effect |
|---|---|
| `"#FF6600"` | 24-bit RGB color |
| `"@#FF6600"` | bold + 24-bit RGB |
| `"bold #FF6600"` | same as above |

**Raw ANSI SGR codes** — legacy format, still supported: `"34;1"`, `"92"`, etc.

### color_mode

| Value | Effect |
|---|---|
| `tag_only` *(default)* | Colors the `[node-N]` prefix and `[TAG]` badge only. ROS 2 severity colors (WARN=yellow, ERROR=red) are preserved. |
| `full_line` | Colors the entire line. At-a-glance group separation; severity colors are overridden. |

---

## Config merging

When a launch file includes other packages, DendROS automatically merges their configs in at runtime — no extra steps needed.

```
ros2 launch my_bringup main.launch.py
             │
             ├── my_bringup/config/dendROS.yaml   ← primary (wins conflicts)
             ├── nav2_bringup/config/dendROS.yaml  ← merged in
             └── slam_toolbox/config/dendROS.yaml  ← merged in
```

DendROS parses the launch file for `get_package_share_directory(…)` / `FindPackageShare(…)` (Python) and `$(find-pkg-share …)` (XML) references, then loads each referenced package's config. The primary package wins any node-name conflicts. One level of includes only.

Config merging is on by default. Toggle it with `dendros config` → **Config merge**.

---

## `dendros init`

Scaffold a `dendROS.yaml` automatically from a package's launch files:

```bash
cd ~/ros2_ws/src/my_bringup
dendros init
```

DendROS scans every `.py` and `.xml` file in `launch/`, extracts all `Node()` / `ComposableNode()` / `<node/>` calls, groups them by source package, and writes `config/dendROS.yaml`. It also patches `CMakeLists.txt` / `setup.py` / `setup.cfg` so the config is installed with the package.

```yaml
# generated config/dendROS.yaml
groups:
  nav2_bringup:
    color: blue
    nodes:
      - bt_navigator
      - controller_server
      - planner_server
  slam_toolbox:
    color: green
    nodes:
      - slam_toolbox

defaults:
  color_mode: tag_only
  show_group_tag: true
  unmatched_color: null
```

### Recursive mode

```bash
dendros init --recursive
```

Follows `IncludeLaunchDescription` / `<include>` references into external packages (BFS, cycle-safe). Packages are found via `ros2 pkg prefix`, `AMENT_PREFIX_PATH`, or as sibling directories in the same workspace `src/` folder. Packages that cannot be located produce a warning but do not abort.

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

### Init behavior options

All behaviors are configurable via `dendros config`:

| Setting | Values | Effect |
|---|---|---|
| `init_on_existing` | `abort` *(default)* / `merge` / `overwrite` | What to do if `config/dendROS.yaml` already exists |
| `init_modify_build` | `on` *(default)* / `off` | Auto-patch `CMakeLists.txt` / `setup.py` / `setup.cfg` |
| `init_color` | `palette` *(default)* / `null` | Assign cycling colors or leave all groups as `color: null` for manual editing |

---

## Global config

Run `dendros config` to open an interactive TUI for setting global defaults that apply across all packages:

```
  DendROS Config  ~/.config/dendROS/defaults.yaml

   ► Color mode          [tag_only]  full_line
     Show group tag      [on]  off
     Unmatched color     null
     Debug mode          [off]  on
     Config merge        [on]  off
     Init: modify build  [on]  off
     Init: on existing   [abort]  merge  overwrite
     Init: color         [palette]  null

  ──────────────────────────────────────────────────
  tag_only — color [node-N] prefix and [TAG] badge only;
  preserves ROS 2 severity colors (WARN=yellow, ERROR=red)

  ↑↓ navigate   Space/→ cycle   e edit text   s save   q quit
```

| Key | Action |
|---|---|
| `↑` / `↓` | Move between fields |
| `→` / `←` / `Space` | Cycle option forward / backward |
| `e` / `Enter` | Edit text field |
| `s` | Save |
| `q` | Quit |

Settings are written to `~/.config/dendROS/defaults.yaml` and used as a baseline whenever `ros2 launch` or `ros2 run` is invoked. Per-package `dendROS.yaml` `defaults:` sections override them.

---

## Environment variables

| Variable | Effect |
|---|---|
| `DENDROS_DEBUG=1` | Print config summary and color map to stderr on startup |
| `DENDROS_DISABLE=1` | Bypass dendROS entirely, call `ros2` directly |

```bash
# Debug: verify dendROS found your config and node names
DENDROS_DEBUG=1 ros2 launch my_pkg my_launch.py

# Temporarily disable without un-sourcing
DENDROS_DISABLE=1 ros2 launch my_pkg my_launch.py
```


## Uninstall

```bash
bash uninstall.sh
```


## Tests

Unit tests run without ROS or Docker:

```bash
python3 -m pytest test/unit/ -v
```

Automated pipeline (generates a timestamped report):

```bash
bash test/run_tests.sh           # unit only
bash test/run_tests.sh --host    # unit + host integration
bash test/run_tests.sh --docker  # unit + docker integration
```

CI runs on every push to `main` via GitHub Actions.
