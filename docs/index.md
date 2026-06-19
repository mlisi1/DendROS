# DendROS

**Colorized ROS 2 terminal output — assign colors to node groups without touching your launch files.**

```
[slam_toolbox-1]  [LOC]  [INFO] [...]: Serialization format: cdr
[bt_navigator-1]  [NAV]  [INFO] [...]: Creating BT navigator
[controller_server-1]  [NAV]  [WARN] [...]: Costmap is empty
[robot_state_publisher-1]  [HW]  [INFO] [...]: Robot description loaded
```

DendROS shadows the `ros2` command with a shell function. When you run `ros2 launch` or `ros2 run`, the output is piped through a colorizer that reads a small YAML config from your package. Every other `ros2` subcommand passes through unchanged.

The name comes from *Dendrobates* — the poison dart frog, famous for its vivid colors.

---

## How it works

1. `ros2 launch my_pkg my_launch.py` is intercepted by a shell function.
2. The real `ros2` binary runs normally — its combined stdout+stderr is piped through `dendROS_pipe.py`.
3. The pipe reads `config/dendROS.yaml` from the launched package, matches the `[node-N]` prefix on each line, and applies group colors.
4. If no config is found, output passes through unchanged. Nothing breaks.

Exit codes are preserved via `${PIPESTATUS[0]}`. Packages without a `dendROS.yaml` are completely unaffected.

---

## Key features

- **Zero-invasive** — no changes to launch files or ROS 2 packages
- **Group-based coloring** — assign colors to logical groups (localization, navigation, hardware…)
- **Badge labels** — optional `[LOC]` / `[NAV]` tags after each node prefix
- **Wildcard matching** — `nav2_*`, `*/amcl`, `*controller*`
- **Config merging** — automatically merges configs from packages referenced in your launch file
- **`dendros init`** — scaffold a config from your launch files in one command
- **`dendros config`** — interactive TUI for global settings
- **Hex truecolor** — `#FF6600`, named colors, raw ANSI codes

---

## Quick start

```bash
git clone https://github.com/mlisi1/DendROS
cd DendROS
bash install.sh
source ~/.bashrc
```

Create `config/dendROS.yaml` in your bringup package:

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
```

Then launch as usual:

```bash
ros2 launch my_bringup main.launch.py
```

See [Installation](installation.md) for the full setup, or [Quick Start](quickstart.md) for a step-by-step walkthrough.
