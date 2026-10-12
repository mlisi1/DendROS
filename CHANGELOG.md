# Changelog

All notable changes to DendROS are listed here, newest first.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-10-12

The headline of this release is **TUI mode**: `ros2 launch` now opens in a full-screen viewer where you scroll, search and filter the log while the launch keeps running. It is the new default; set `launch_mode: classic` to keep the 1.0 output.

### Added

**TUI mode** (`launch_mode: tui`, the default, for `ros2 launch`) — [docs](https://mlisi1.github.io/DendROS/launch-tui/)

- Full-screen log viewer with scrollback (`tui_scrollback_lines`, default 5000), line wrapping, a scrollbar and resize support.
- Mouse wheel scrolling, and click-and-drag selection that copies to the clipboard through OSC 52 and `xclip` / `xsel` / `wl-copy`.
- Crash and parameter-change alerts stay pinned in the header instead of scrolling away.
- Falls back to classic output automatically when the output is piped or redirected, or when the terminal can't run it.

**Console commands** (press `\` in TUI mode) — [docs](https://mlisi1.github.io/DendROS/tui-console/)

- `focus <node>...` shows only the listed nodes. It matches the process name or the ROS logger name, so components inside a container can be focused one by one.
- `level <lvl>` shows lines at a severity or worse. Tracebacks and other lines without a level always stay visible.
- `grep <text>` is a live text filter with the matches highlighted.
- `find <text>` searches the scrollback; Tab and Shift+Tab step through the matches.
- `mute <node>` and `unmute <node|all>` hide and restore noisy nodes.
- `mark [label]` inserts a timestamped separator line.
- `tee <file> [-c] [-a]` saves the lines currently shown to a file, optionally with colors or appending.
- `clear` removes every filter and mute; `help` lists every command and key.
- Filters combine, and Esc removes the most recent one at a time.
- Tab completion for commands, node names and levels, and Up/Down command history.

**Remote control and reopen** — [docs](https://mlisi1.github.io/DendROS/tui-remote/)

- `dendros focus`, `find`, `grep`, `level`, `mute`, `unmute`, `mark`, `tee` and `clear` send the same commands to a running TUI from another terminal.
- `dendros reopen` reopens the last TUI run of the current terminal after it has ended, with its full scrollback.

**Runtime control** — [docs](https://mlisi1.github.io/DendROS/runtime-control/)

- `dendros disable` and `dendros enable` switch DendROS off and on in every terminal, including launches that are already running, without restarting them.

**Output options**

- `show_timestamp` and `show_logger_name` hide the `[timestamp]` and `[logger]` brackets of node log lines for a terser output. Both can be set globally or per package.
- `ignore_bold` strips bold from every color, for terminals that brighten bold text but not backgrounds and so show a badge in a different shade than its node's text.

**Other**

- A `package.xml`, so the repository can be indexed as a ROS package.
- Documentation: new pages for TUI mode, console commands, remote control, enable and disable, troubleshooting and a ROS 2 CLI overview. Every screenshot was redone, and each console command has a short recording.

### Changed

- `ros2 launch` opens in the TUI viewer by default (`launch_mode: tui`). `ros2 run`, piped or redirected output, and every other command are unchanged.
- `dendros config` groups its settings into tabs (Output, CLI, Unmatched, System, Diagnostics, Param Alerts, Init) instead of one long list.
- `dendros init` must be run from the package root, the folder that contains `package.xml`. From a subfolder it tells you where to run it instead of guessing.
- `dendros init` writes nothing when it finds no nodes. Previously it created an empty config and patched the build files anyway.
- `dendros init` colors its warnings yellow and its errors red, like ROS 2 does.
- The `[dendROS]` tag uses the same brand blue and orange everywhere it is printed.

### Fixed

- `dendros init` on `ament_cmake` packages added an install rule that put `dendROS.yaml` in `share/<pkg>/` instead of `share/<pkg>/config/`, so the config was never found. See the upgrade notes below.
- `uninstall.sh` now works as root (for example in Docker), removes only the two lines the installer added to `.bashrc` instead of every line mentioning `dendROS`, and cleans up saved TUI runs and other runtime files. Your settings file is kept.
- The docs gave `after` as the default `tag_position`; the default has always been `before`.

### Upgrading from 1.0

- Pull the repository and run `bash install.sh` again, then open a new terminal or `source ~/.bashrc`.
- `ros2 launch` now opens in the viewer, also if you saved your settings with 1.0. To keep the old scrolling output, run `dendros config` and set **Launch mode** to `classic` in the Output tab, or add `launch_mode: classic` to `~/.config/dendROS/defaults.yaml`.
- If you ran `dendros init` on an `ament_cmake` package with 1.0, open its `CMakeLists.txt` and change `install(DIRECTORY config/` to `install(DIRECTORY config` (no trailing slash), then rebuild. `ament_python` packages are not affected.

## [1.0.0] - 2026-07-01

First release.

### Added

- Group-based coloring of `ros2 launch` and `ros2 run` output from a `dendROS.yaml` in each package: colors, badges, per-group options, wildcard node matching and keyword highlighting.
- Named, extended, hex and raw ANSI colors, and `tag_only` or `full_line` coloring.
- `dendros init` to generate a config from a package's launch files, with `--recursive` and `--labels`.
- `dendros config`, an interactive editor for the global settings.
- Config merging: configs of packages included by a launch file are merged in automatically.
- Crash alert banner, Python traceback highlighting and parameter change alerts.
- Colorized `ros2 node list`, `node info`, `topic list`, `service list`, `action list`, `param list` and `param describe`, sharing the colors of the running launch.
- `DENDROS_DISABLE=1` and `DENDROS_DEBUG=1` environment variables.
- Host and Docker installation.

[1.1.0]: https://github.com/mlisi1/DendROS/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/mlisi1/DendROS/releases/tag/v1.0.0
