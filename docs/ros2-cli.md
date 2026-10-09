# ROS 2 CLI Overview

Besides `ros2 launch` and `ros2 run`, DendROS colorizes the output of the most common `ros2` introspection commands with the same group colors and badges. There's nothing extra to configure.

| Command | What's colored | Page |
|---|---|---|
| `ros2 node list` | Each node in its group color | [ros2 node list](node-list.md) |
| `ros2 node info` | The node, and every topic, service and action by the node that provides it | [ros2 node info](node-info.md) |
| `ros2 topic list` | Topics by their publisher's group, with publisher/subscriber counts | [ros2 topic list](topic-list.md) |
| `ros2 service list` | Services by owning node; standard ROS 2 services dimmed or hidden | [ros2 service list](service-list.md) |
| `ros2 action list` | Actions by owning node | [ros2 action list](action-list.md) |
| `ros2 param list` | Node headers colored, parameter names dimmed | [ros2 param list](param-list.md) |
| `ros2 param describe` | Parameter name in the node's color, labels dimmed | [ros2 param describe](param-describe.md) |

Every other `ros2` subcommand is passed to the real `ros2` binary untouched.

---

## Where the colors come from

1. **A running launch.** Every `ros2 launch`/`ros2 run` started through DendROS writes its node-to-color map to `~/.config/dendROS/node_colors.yaml`. CLI commands in any other terminal read it, so `ros2 node list` matches the colors of the launch you're looking at, including nodes discovered by their logger name.
2. **Installed configs.** Without a running launch, DendROS reads the `dendROS.yaml` files of every package on `AMENT_PREFIX_PATH`.

Nodes that match no group follow the [unmatched](global-config.md#unmatched-nodes) settings.

---

## Settings that apply to all CLI commands

| Setting | Key | Description |
|---|---|---|
| **Show tag (CLI)** | `show_tag_cli` | Show `[TAG]` badges in CLI output. Independent of badges in launch output. |
| **Tag style** | `tag_style` | `normal` or `inverted` badges, shared with launch output. |
| **Ignore bold** | `ignore_bold` | Strip bold from every color (terminal compatibility). |

Command-specific settings (`show_default_services`, `topic_sort`) are described on each command's page. All settings are in the **CLI** tab of [`dendros config`](global-config.md#cli-commands).

---

## Notes

- `dendros disable` and `DENDROS_DISABLE=1` turn off CLI colorization too, see [Enable & Disable](runtime-control.md).
- If the output is piped or redirected, it's still colorized. Use `DENDROS_DISABLE=1` for plain text.
