# Troubleshooting

Common problems and how to fix them. When in doubt, start with [debug mode](runtime-control.md#debug-output-dendros_debug).

---

## Setup

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

---

## Colors

??? warning "A node's [TAG] badge is a different shade than its own text"
    Some terminals brighten bold *foreground* text but never brighten backgrounds — since a
    node's regular text is bold foreground and its inverted `[TAG]` badge uses that same
    color as a background, the two can end up looking like different shades of the same
    color on terminals that do this. It's a terminal rendering quirk, not a config problem:


    === "Mismatched Colors"
        <div class="term">
          <div class="term-bar">
            <div class="term-dots">
              <div class="term-dot term-dot-red"></div>
              <div class="term-dot term-dot-yellow"></div>
              <div class="term-dot term-dot-green"></div>
            </div>
            <div class="term-title">Before — ignore_bold off (default)</div>
          </div>
          <div class="term-body-image">
          <p align="center">
        <img src="../assets/images/screenshots/mismatching_colors.png" width="800" alt="Tag and node text rendered as different shades"/>
        </p>
        </div>
        </div>

    === "Correct Colors"

        <div class="term">
          <div class="term-bar">
            <div class="term-dots">
              <div class="term-dot term-dot-red"></div>
              <div class="term-dot term-dot-yellow"></div>
              <div class="term-dot term-dot-green"></div>
            </div>
            <div class="term-title">After — ignore_bold on</div>
          </div>
          <div class="term-body-image">
          <p align="center">
        <img src="../assets/images/screenshots/correct_colors.png" width="800" alt="Tag and node text rendered as the same shade"/>
        </p>
        </div>
        </div>

    Fix it by enabling **Ignore bold** in `dendros config` (Output tab), or setting
    `ignore_bold: true` in `~/.config/dendROS/defaults.yaml` directly. This strips the bold
    modifier everywhere colors are resolved — `ros2 launch`/`run`, the TUI, and every
    `ros2 node/service/action/param/topic` CLI command — so hue stays consistent regardless
    of how your terminal handles bold. See [Global Settings](global-config.md#output-launch-run).

??? note "Colors may look different across terminals"
    ROS 2's own log-level colors, and any *standard* named color you use in `dendROS.yaml`
    (`red`, `blue`, `green`, …), are rendered using **your terminal emulator's own color
    theme** — that's how ANSI works, with or without DendROS. The exact same session can
    genuinely look different depending on what you're running it in:

    

    === "Terminator"

        <div class="term">
          <div class="term-bar">
            <div class="term-dots">
              <div class="term-dot term-dot-red"></div>
              <div class="term-dot term-dot-yellow"></div>
              <div class="term-dot term-dot-green"></div>
            </div>
            <div class="term-title">Terminator</div>
          </div>
          <div class="term-body-image">
          <p align="center">
        <img src="../assets/images/screenshots/Terminator.png" width="800" alt="Same session in Terminator"/>
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
            <div class="term-title">Konsole</div>
          </div>
          <div class="term-body-image">
          <p align="center">
        <img src="../assets/images/screenshots/Konsole.png" width="800" alt="Same session in Konsole"/>
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
            <div class="term-title">Yakuake</div>
          </div>
          <div class="term-body-image">
          <p align="center">
        <img src="../assets/images/screenshots/yakuake.png" width="800" alt="Same session in Yakuake"/>
        </p>
        </div>
        </div>

    Use [extended/hex colors](colors.md) (`"#FF6600"`, `teal`, `coral`, …) instead of the 8
    standard names if you want an exact, portable color regardless of terminal theme. If
    instead a node's text and its `[TAG]` badge look like different shades, see the entry
    above.

---

## TUI mode

??? warning "`ros2 launch` still shows classic output"
    Check that `launch_mode: tui` is set in `~/.config/dendROS/defaults.yaml` (or **Launch
    mode** in the **Output** tab of `dendros config`). TUI mode also falls back to classic
    output on purpose when:

    - the command is `ros2 run` (TUI mode is for `ros2 launch` only)
    - stdout is redirected or piped (`| tee`, `> file`)
    - curses can't start in the terminal

    See [TUI Mode](launch-tui.md#when-tui-mode-is-used).

??? warning "Copying with the mouse does nothing"
    DendROS copies through OSC 52 and, if installed, `xclip`/`xsel`/`wl-copy`. Some
    terminals (several VTE-based ones, Terminator for example) ignore OSC 52. Install a
    clipboard tool:
    ```bash
    sudo apt install xclip          # X11
    sudo apt install wl-clipboard   # Wayland
    ```
    If no tool is found, the TUI header says `-- copy needs xclip/xsel/wl-copy (none found) --`.

??? warning "Colors in the TUI look slightly different from classic mode"
    The TUI draws with the terminal's 256-color palette, so hex and extended colors are
    shown as the nearest of those 256 colors. Classic mode shows them exactly.

??? warning "`dendros focus` says unknown node"
    A node can only be focused or muted after it has printed at least one line. Use Tab
    completion in the console bar (`\focus ` then ++tab++) to see the names the TUI knows.

??? warning "`dendros reopen` says there's no saved run"
    Runs are saved per terminal: reopen from the same terminal that ran the launch. Only TUI
    launches are saved, not classic-mode ones. See
    [Reopen the last run](tui-remote.md#reopen-the-last-run).
