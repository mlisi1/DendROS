# Console Commands

In [TUI mode](launch-tui.md), press ++backslash++ to open the console bar at the bottom of the screen. Type a command and press ++enter++. ++escape++ or ++backslash++ closes the bar without running anything.

```text
\focus planner_server
\level warn
\find timeout
```

| Command | What it does |
|---|---|
| `focus <node>` | Show only one node's lines |
| `level <lvl>` | Show only lines at a severity or worse |
| `grep <text>` | Show only lines containing some text |
| `find <text>` | Jump between lines containing some text |
| `mute <node>` | Hide one node's lines |
| `unmute <node\|all>` | Show a muted node again |
| `clear` | Back to the full, unfiltered log |
| `help` | Show every command and key |

Filtering never deletes anything. Lines that arrive while a filter is active are still recorded, and they reappear as soon as you remove the filter.

All of these commands can also be sent from another terminal, see [Remote Control & Reopen](tui-remote.md).

---

## What it looks like

<div class="screenshot-placeholder">
<div class="sp-icon">⌨️</div>
<p class="sp-label">Console bar with Tab completion</p>
<p class="sp-hint">screenshots/tui_console.png</p>
</div>

---

## `focus <node>`

Shows only the lines of one node.

```text
\focus talker
```

You can use either the launch process name (the `talker` in `[talker-1]`) or the node's ROS logger name. A leading `/` is optional.

!!! tip "Composable nodes"
    Components loaded into a container print under the container's process name, but each one logs under its own logger name. `focus my_container` shows the container and all its components; `focus my_component` shows just that component.

Only nodes that have printed at least one line (including the launch's own `process started` line) can be focused. An unknown name shows an error in the header and leaves the current view alone.

---

## `level <lvl>`

Shows only lines at the given severity or worse. Levels, from lowest to highest: `debug`, `info`, `warn`, `error`, `fatal` (`warning` also works, and case doesn't matter).

```text
\level warn     # WARN, ERROR and FATAL
\level          # remove the level filter
```

Lines without a severity, such as Python tracebacks, `print()` output and DendROS alerts, always stay visible, so a crash is never hidden by a level filter.

---

## `grep <text>`

Shows only lines containing the text.

```text
\grep goal
\grep           # remove the grep filter
```

Matching uses smart case: all-lowercase text matches regardless of case, and any uppercase letter makes the match case-sensitive.

The matching text is highlighted in bold, underlined orange, like `grep --color`. If a `find` is active too, its highlighting takes precedence where the two overlap.

grep is a live filter. If nothing matches yet, the view is empty until a matching line arrives.

---

## Combining filters

`focus`, `level` and `grep` combine: a line is shown only if it passes all of them.

```text
\focus planner_server
\level warn
\grep timeout
```

The active filters are shown in the header, for example `focus planner_server · level warn · grep "timeout"`.

Running the same command again replaces its value, so `\focus controller_server` switches the focus without touching the level or grep filter.

---

## `find <text>`

Searches the whole scrollback and jumps to the newest match. Unlike `grep`, nothing is hidden: you move between matches in the full log.

```text
\find exception
```

| Key | Effect |
|---|---|
| ++tab++ | Previous (older) match |
| ++shift+tab++ | Next (newer) match |
| ++escape++ | End the search |

Every match is highlighted, and the current line's matches are drawn in orange. The header shows the search and your position, for example `find "exception"  3/7`. Positions count from the oldest match, so when new matches arrive below you, the total grows while your position stays the same.

While a search is active the view stays on the current match instead of following new output. Press ++end++, or scroll back to the bottom, to follow the tail again.

`find` uses the same smart case as `grep`, and searches only lines that pass the current filters. If nothing matches, the previous search (if any) stays as it was.

---

## `mute <node>` / `unmute <node|all>`

Hides a noisy node's lines, without switching into a mode.

```text
\mute camera_driver
\unmute camera_driver
\unmute all
```

Nodes are matched like in `focus`: muting a container hides its components, muting a component hides only that component.

The header shows how many nodes are muted, for example `2 nodes muted`. ++escape++ does not unmute anything; only `unmute` and `clear` do. Mutes are saved with the run, so [`dendros reopen`](tui-remote.md#reopen-the-last-run) shows the run with the same nodes muted.

---

## `clear`

Removes every filter (`focus`, `level`, `grep`), every mute, and ends any `find`. The view goes back to the full, live log.

---

## `help`

Opens an overlay listing every command and key. Scroll it with the arrow keys, ++page-up++ / ++page-down++ or the mouse wheel; close it with ++escape++, ++q++ or ++backslash++.

---

## Leaving modes with Esc

`focus`, `level`, `grep` and `find` are modes. With the console closed, ++escape++ exits the most recent one, so you can back out one step at a time:

```text
\focus planner_server      # 1st
\grep goal                 # 2nd
\find aborted              # 3rd
Esc  → ends the find
Esc  → removes the grep filter
Esc  → removes the focus
```

The header hint always names the mode the next ++escape++ will exit, for example `Esc exit grep`.

---

## Tab completion

In the console bar, ++tab++ completes:

- command names
- node names, for `focus` and `mute`
- muted node names and `all`, for `unmute`
- severity names, for `level`

If several completions match, the first ++tab++ fills in the part they have in common and lists the candidates in the bar. Pressing ++tab++ again cycles through them, ++shift+tab++ cycles backwards.

---

## Command history

In the console bar, ++up++ and ++down++ step through the commands you've entered during this launch, like in a shell. Whatever you were typing comes back when you press ++down++ past the newest one.

Every submitted command is kept, including ones that failed, so a typo can be recalled and fixed. History lasts for the whole launch, including across `dendros disable`/`enable`, but isn't saved between launches.

---

## Keys reference

| Key | Where | Effect |
|---|---|---|
| ++backslash++ | anywhere | Open the console bar |
| ++enter++ | console bar | Run the command |
| ++escape++ / ++backslash++ | console bar | Close the bar |
| ++tab++ / ++shift+tab++ | console bar | Complete / cycle completions |
| ++up++ / ++down++ | console bar | Previous / next command |
| ++tab++ / ++shift+tab++ | during `find` | Older / newer match |
| ++escape++ | log view | Exit the most recent mode |
| ++page-up++ / ++page-down++, ++up++ / ++down++, wheel | log view | Scroll |
| ++home++ / ++end++ | log view | Oldest line / follow the live tail |
| Mouse drag | log view | Select and copy |
| ++q++ | after the launch exits | Quit |

---

## Notes

- Search text and grep text can't contain `\`, since typing it closes the console bar.
- Node names are matched by the node's real identity, not by the displayed text, so filters work the same with any `tag_position`, `show_timestamp` or `show_logger_name` setting.
- Filters only change what is displayed. Copying, saving for `dendros reopen` and the scrollback limit all work on the full log.
