# Config Merging

When a launch file includes other packages, DendROS automatically merges their `dendROS.yaml` configs at runtime.

---

## How it works

<div class="term">
  <div class="term-bar">
    <div class="term-dots">
      <div class="term-dot term-dot-red"></div>
      <div class="term-dot term-dot-yellow"></div>
      <div class="term-dot term-dot-green"></div>
    </div>
    <div class="term-title">ros2 launch my_bringup main.launch.py</div>
  </div>
  <div class="term-body">ros2 launch my_bringup main.launch.py
         │
         ├── <span class="t-green">my_bringup/config/dendROS.yaml</span>  <span class="t-dim">← primary (wins conflicts)</span>
         ├── <span class="t-blue">nav2_bringup/config/dendROS.yaml</span> <span class="t-dim">← merged in</span>
         └── <span class="t-cyan">slam_toolbox/config/dendROS.yaml</span> <span class="t-dim">← merged in</span></div>
</div>

When `ros2 launch` is intercepted, DendROS:

1. Parses the launch file for package references.
2. Locates each referenced package's `dendROS.yaml` via `ros2 pkg prefix` or `AMENT_PREFIX_PATH`.
3. Merges all configs — the **primary package wins** any node-name conflicts.
4. Processes output with the merged config.

!!! info "Merge depth"
    Config merging is **one level deep only** — packages included by included packages are not recursively scanned (for the time being).

---

## Supported formats

=== "Python (.py)"

    ```python
    get_package_share_directory('nav2_bringup')
    FindPackageShare('slam_toolbox')
    ```

=== "XML (.xml / .launch)"

    ```xml
    <include file="$(find-pkg-share nav2_bringup)/launch/bringup.launch.py"/>
    ```

---

## Conflict resolution

When the same node name appears in multiple configs, the primary package's definition wins.
Among secondaries, the first one found in parse order wins.

---

## Toggling

Config merging is **on** by default. To disable:

```bash
dendros config   # navigate to "Config merge" → off
```

Or per-package:

```yaml
defaults:
  config_merge: false
```
