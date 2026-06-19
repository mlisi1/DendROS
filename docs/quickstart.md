# Quick Start

A complete walkthrough from zero to colorized output.

---

## Step 1 — Install

```bash
git clone https://github.com/mlisi1/DendROS
cd DendROS && bash install.sh && source ~/.bashrc
```

---

## Step 2 — Scaffold a config

Run `dendros init` from inside your bringup package:

```bash
cd ~/ros2_ws/src/my_bringup
dendros init
```

!!! tip "Recursive mode"
    If your launch file includes other packages, use `--recursive` to follow them:
    ```bash
    dendros init --recursive          # follow IncludeLaunchDescription / <include>
    dendros init --recursive --labels # also auto-generate short badge labels
    ```

<div class="term">
  <div class="term-bar">
    <div class="term-dots">
      <div class="term-dot term-dot-red"></div>
      <div class="term-dot term-dot-yellow"></div>
      <div class="term-dot term-dot-green"></div>
    </div>
    <div class="term-title">dendros init --recursive --labels</div>
  </div>
  <div class="term-body"><span class="t-dim">[dendROS] package: my_bringup</span>
<span class="t-dim">[dendROS] scanning (recursive) launch files…</span>
<span class="t-dim">[dendROS]   main.launch.py: 2 node(s)</span>
<span class="t-dim">[dendROS] found references to: nav2_bringup, slam_toolbox</span>
<span class="t-dim">[dendROS]   nav2_bringup/bringup_launch.py [install]: 8 node(s)</span>
<span class="t-dim">[dendROS]   slam_toolbox/online_async_launch.py [source]: 1 node(s)</span>
<span class="t-dim">[dendROS] found 11 node(s) in 3 group(s)</span>
<span class="t-green">[dendROS] created config/dendROS.yaml</span></div>
</div>

---

## Step 3 — Edit the config

Open the generated `config/dendROS.yaml` and set colors and labels:

```yaml
groups:
  nav2_bringup:
    color: "bold green"
    label: "NAV"
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

See [Configuration](configuration.md) for the full format and [Colors](colors.md) for all accepted values.

---

## Step 4 — Build and launch

```bash
cd ~/ros2_ws
colcon build --packages-select my_bringup
source install/setup.bash
ros2 launch my_bringup main.launch.py
```

!!! success "Done"
    Your terminal output is now colorized. No other changes to your launch files or ROS 2 setup are needed.

![Colorized launch output](assets/images/screenshots/terminal_output.png)

---

## Troubleshooting

??? warning "No colors showing"
    Run with debug mode:
    ```bash
    DENDROS_DEBUG=1 ros2 launch my_bringup main.launch.py
    ```
    If you see `passthrough mode`, the config was not discovered. Verify:

    - The package was built and you sourced `install/setup.bash`.
    - `config/dendROS.yaml` is installed. Check `CMakeLists.txt` for:
      ```cmake
      install(DIRECTORY config/ DESTINATION share/${PROJECT_NAME})
      ```

??? warning "Nodes not matching expected colors"
    Check the debug summary — it prints each group and its patterns. Compare against raw output:
    ```bash
    DENDROS_DISABLE=1 ros2 launch my_bringup main.launch.py 2>&1 | grep '^\['
    ```
    Node names are matched after stripping the `-N` suffix. Use wildcards (`nav2_*`) for nodes you don't know in advance.

??? note "Temporarily disable"
    ```bash
    DENDROS_DISABLE=1 ros2 launch my_bringup main.launch.py
    ```
    Calls the real `ros2` directly without un-sourcing or modifying anything.
