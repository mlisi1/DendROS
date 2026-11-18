# Self-test (`dendros test`)

`dendros test` checks that DendROS can run in the current terminal and shows which colors the terminal can display. It does not run the unit tests. Run it after installing, when you switch to another terminal emulator, or before you report a bug.

```bash
dendros test
```

=== "Terminator"

    <div class="term">
      <div class="term-bar">
        <div class="term-dots">
          <div class="term-dot term-dot-red"></div>
          <div class="term-dot term-dot-yellow"></div>
          <div class="term-dot term-dot-green"></div>
        </div>
        <div class="term-title">dendros test (Terminator)</div>
      </div>
      <div class="term-body-image">
      <p align="center">
    <img src="../assets/images/screenshots/dendros_test.png" width="900" alt="dendros test output in Terminator"/>
    </p>
    </div>
    </div>

=== "Konsole"

    <div class="term">
      <div class="term-bar">
        <div class="term-dots">
          <div class="term-dot term-dot-red"></div>
          <div class="term-dot term-dot-yellow"></div>
          <div class="term-dot term-dot-green"></div>
        </div>
        <div class="term-title">dendros test (Konsole)</div>
      </div>
      <div class="term-body-image">
      <p align="center">
    <img src="../assets/images/screenshots/dendros_test_konsole.png" width="900" alt="dendros test output in Konsole"/>
    </p>
    </div>
    </div>

=== "Yakuake"

    <div class="term">
      <div class="term-bar">
        <div class="term-dots">
          <div class="term-dot term-dot-red"></div>
          <div class="term-dot term-dot-yellow"></div>
          <div class="term-dot term-dot-green"></div>
        </div>
        <div class="term-title">dendros test (Yakuake)</div>
      </div>
      <div class="term-body-image">
      <p align="center">
    <img src="../assets/images/screenshots/dendros_test_yakuake.png" width="900" alt="dendros test output in Yakuake"/>
    </p>
    </div>
    </div>

The same output in three terminals. **Terminator** (default Tango palette) is the reference: DendROS is designed and documented against it. **Konsole** and **Yakuake** use the Breeze scheme and draw bold text in a brighter shade, so the named colors, the bold column and the bold-vs-badge row look different there. Your launches look different in exactly the same way, in the TUI and in classic output.

Each check is marked:

| Mark | Meaning |
|---|---|
| <span class="t-green">✔</span> | Works. |
| <span class="t-yellow">!</span> | Works, but with less: a fallback is in use, or a setting is ignored. |
| <span class="t-red">✘</span> | Broken. DendROS, or part of it, won't work until it is fixed. |
| <span class="t-dim">·</span> | Information only. |

The command exits with status `1` if any check fails, so a script can run it too.

---

## Checks

### Dependencies

| Check | Fails / warns when |
|---|---|
| Python | Older than 3.8 (fails). |
| PyYAML | Not importable (fails): configs can't be read. Install with `pip3 install pyyaml`. |
| curses | Not importable (warns): `ros2 launch` uses classic output. |
| ros2 | No `ros2` on `PATH` (fails): source `/opt/ros/<distro>/setup.bash`. Shows `ROS_DISTRO`. |
| rclpy | Not importable (warns): [`ros2 node info`](node-info.md) and [`ros2 topic list`](topic-list.md) use slower CLI fallbacks. |
| clipboard | No `xclip`, `xsel` or `wl-copy` (warns): copying in the TUI uses OSC 52 only, which some terminals ignore. See [Troubleshooting](troubleshooting.md#tui-mode). |

### Shell and config

| Check | Fails / warns when |
|---|---|
| ros2 wrapper | `ros2` in this shell is not the DendROS function (fails), for example an alias or another function defined after `dendROS.sh` is sourced. |
| status | DendROS is [disabled](runtime-control.md) in this shell (`DENDROS_DISABLE`) or system-wide (`dendros disable`) (warns). |
| config dir | `~/.config/dendROS` can't be written (fails): shared node colors, `disable`, remote commands and `reopen` need it. |
| global config | `defaults.yaml` isn't valid YAML (fails: every setting falls back to its default), or has unknown keys or invalid values (warns). DendROS ignores both without saying so, so a typo like `tag_positon` would otherwise go unnoticed. |
| launch mode | Shows `tui` or `classic`. |
| package configs | Lists every installed package with a `config/dendROS.yaml` (found through `AMENT_PREFIX_PATH`, so source your workspace first), and fails for any that can't be loaded. Such a package's launches run without colors. |

### Terminal

| Check | Shows |
|---|---|
| terminal | `TERM` and `COLORTERM`. `TERM=dumb` or unset warns. |
| size | Columns × rows. |
| 24-bit color | Whether the terminal says it supports 24-bit color (`COLORTERM=truecolor`). Many terminals support it without saying so: the gradient chart shows it either way. |
| TUI | Opens the TUI for two seconds (any key closes it sooner) and draws the 256-color palette through the same code as a launch. Fails if curses can't start; a launch would then use classic output. |
| TUI colors | How many colors the TUI can use. Fewer than 256 warns: node colors are then mapped to the nearest of the 8 or 16 base colors. Inside `docker exec` set `-e TERM=xterm-256color`. |
| TUI palette | Whether the TUI can draw its console bar in the exact brand blue and orange, or uses the nearest stock colors. |

---

## Color charts

### Named colors

The 8 [named colors](colors.md#named-colors) with each modifier (`light`, `bold`, `dark`) and as a normal and an inverted `[TAG]` badge. These use the terminal's own 16-color palette, so they differ the most between terminals and themes.

### Extended named colors

Each [extended color](colors.md#extended-named-colors) as two swatches: on the left the exact 24-bit color, used in classic output and in the `ros2` CLI commands; on the right the nearest of the 256 colors, which is what the TUI draws.

### 256-color palette

Every color the TUI can draw: the 16 system colors with their numbers, the 6×6×6 color cube and the grey ramp. Hex and extended colors in the TUI are shown as the nearest color of this palette.

### 24-bit gradients

Hue, grey and brand-blue-to-orange gradients in 24-bit color. If they are smooth, hex colors (`#FF6600`) and extended colors are shown exactly. If they show steps or bands, the terminal approximates them.

### Text attributes and bold

A sample of bold, dim, italic, underline, reverse and strikethrough. DendROS uses bold, dim (for unmatched nodes and default services) and reverse (for inverted badges).

The next row shows bold text next to an inverted badge in the same color. If the text is brighter than the badge background, the terminal brightens bold text only: set [`ignore_bold: true`](global-config.md) so that both use the same shade. See [Troubleshooting](troubleshooting.md#colors).

### Preview with your settings

Three sample nodes and a launch message, drawn with your global display settings (`tag_position`, `tag_style`, `color_mode`, `show_timestamp`, `show_logger_name`, `show_tag_launch`, `colorize_launch_msgs`). Change them with [`dendros config`](global-config.md) and run `dendros test` again to compare.

---

## Options

| Option | Effect |
|---|---|
| `--no-tui` | Don't open the TUI. |
| `--no-colors` | Only run the checks, without the color charts. |

When the output is not a terminal (`dendros test > report.txt`), the TUI is not opened and the charts are written as ANSI escape codes. Attach that file to a bug report: it records the dependency versions, the config problems and the terminal's color support.
