# Quick Start

This guide walks you through adding DendROS to an existing bringup package.

---

## Step 1 — Install

```bash
git clone https://github.com/mlisi1/DendROS
cd DendROS
bash install.sh && source ~/.bashrc
```

---

## Step 2 — Scaffold a config (recommended)

Run `dendros init` from inside your bringup package:

```bash
cd ~/ros2_ws/src/my_bringup
dendros init
```

DendROS scans your `launch/` directory, extracts all node names, groups them by source package, and writes `config/dendROS.yaml`. It also patches `CMakeLists.txt` / `setup.py` / `setup.cfg` to install the config.

For packages that include other launch files, use `--recursive` to follow them:

```bash
dendros init --recursive
```

See [`dendros init`](dendros-init.md) for full details.

---

## Step 3 — Edit the config

Open the generated `config/dendROS.yaml` and fill in labels and adjust colors:

```yaml
groups:
  nav2_bringup:
    color: "bold green"
    label: "NAV"          # ← fill in a short badge label
    nodes:
      - bt_navigator
      - controller_server
      - planner_server

  slam_toolbox:
    color: "bold blue"
    label: "LOC"
    nodes:
      - slam_toolbox

defaults:
  color_mode: tag_only
  show_group_tag: true
  unmatched_color: null
```

See [Configuration](configuration.md) for the full config reference, and [Colors](colors.md) for all accepted color formats.

---

## Step 4 — Build and launch

```bash
cd ~/ros2_ws
colcon build --packages-select my_bringup
source install/setup.bash
ros2 launch my_bringup main.launch.py
```

Your terminal output is now colorized. No other changes needed.

---

## Troubleshooting

**No colors showing?**

Run with debug mode to confirm DendROS found the config:

```bash
DENDROS_DEBUG=1 ros2 launch my_bringup main.launch.py
```

If you see `passthrough mode`, the config file was not found. Make sure:

- The package was built and `install/setup.bash` was sourced.
- `config/dendROS.yaml` is installed to `share/my_bringup/config/` (check `CMakeLists.txt` or `setup.py`).

**Want to disable temporarily?**

```bash
DENDROS_DISABLE=1 ros2 launch my_bringup main.launch.py
```
