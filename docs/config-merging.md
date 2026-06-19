# Config Merging

When a launch file includes other packages, DendROS automatically merges their `dendROS.yaml` configs at runtime — no extra steps needed.

---

## How it works

```
ros2 launch my_bringup main.launch.py
             │
             ├── my_bringup/config/dendROS.yaml   ← primary (wins conflicts)
             ├── nav2_bringup/config/dendROS.yaml  ← merged in
             └── slam_toolbox/config/dendROS.yaml  ← merged in
```

When `ros2 launch` is intercepted, DendROS:

1. Parses the launch file for package references.
2. Finds each referenced package's `dendROS.yaml`.
3. Merges all configs — the primary package wins any node-name conflicts; first secondary wins among secondaries.
4. Processes output with the merged config.

Merge depth is one level — packages included by *included* packages are not recursively scanned.

---

## Supported launch file formats

**Python (`.py`)**

```python
# These patterns are recognized:
get_package_share_directory('nav2_bringup')
FindPackageShare('slam_toolbox')
```

**XML (`.xml` / `.launch`)**

```xml
<!-- This pattern is recognized: -->
<include file="$(find-pkg-share nav2_bringup)/launch/bringup.launch.py"/>
```

---

## Conflict resolution

When two configs define the same node name, the primary package's definition wins:

```
my_bringup/dendROS.yaml     →  bt_navigator: bold blue   ← wins
nav2_bringup/dendROS.yaml   →  bt_navigator: bold green  ← ignored
```

Among secondary packages, the first one listed (in parse order) wins.

---

## Toggling config merge

Config merging is on by default. To disable it:

```bash
dendros config
# navigate to "Config merge" → set to off
```

Or add to your package's `dendROS.yaml`:

```yaml
defaults:
  config_merge: false
```

!!! tip
    If you have all nodes defined in your primary bringup package's config, merging has no effect. It's most useful when each package maintains its own `dendROS.yaml` independently.
