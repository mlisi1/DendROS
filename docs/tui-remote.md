# Remote Control & Reopen

Two ways to work with a [TUI](launch-tui.md) launch from outside it: send console commands from another terminal, and reopen a run after it has ended.

---

## Sending commands from another terminal

Every [console command](tui-console.md) except `help` has a `dendros` equivalent. Run it in any terminal and the running TUI applies it within about a second, as if you had typed it into its console bar.

```bash
dendros focus planner_server
dendros level warn
dendros grep timeout
dendros find exception
dendros mute camera_driver
dendros unmute all
dendros clear
dendros mark sending goal
```

| Command | Same as |
|---|---|
| `dendros focus <node>...` | `\focus <node>...` |
| `dendros level [lvl]` | `\level [lvl]` (no level removes the filter) |
| `dendros grep [text]` | `\grep [text]` (no text removes the filter) |
| `dendros find <text>` | `\find <text>` |
| `dendros mute <node>` | `\mute <node>` |
| `dendros unmute <node\|all>` | `\unmute <node\|all>` |
| `dendros clear` | `\clear` |
| `dendros mark [label]` | `\mark [label]` |

Typical use: the launch runs in one pane while you work in another, and you want to look at a single node without switching panes.

Errors (unknown node, no matches) are shown in the TUI's header, not in the terminal that sent the command.

!!! note "One TUI at a time"
    Commands aren't addressed to a specific launch. Each command is delivered to exactly one TUI: if several TUI launches are running, whichever one checks first receives it. If none is running, the command is dropped: a newly started TUI launch ignores commands sent before it started.

---

## Reopen the last run

```bash
dendros reopen
```

When a TUI launch ends, DendROS saves its log. `dendros reopen` opens that log again in the same viewer, so you can keep reading it after you've quit, or after the terminal has been cleared.

<div class="screenshot-placeholder">
<div class="sp-icon">⏪</div>
<p class="sp-label">dendros reopen: reviewing a finished run</p>
<p class="sp-hint">screenshots/tui_reopen.png</p>
</div>

- The header shows which launch it was and when it ended, for example `-- last run: my_bringup main.launch.py, ended 14:32 --`.
- Scrolling, copying and every console command work as in a live run. ++q++ quits.
- The crash banner from the end of the run is shown again.
- Nodes that were muted when the run ended are still muted. Muting or unmuting during the review is saved, so the next `dendros reopen` matches.
- The whole log is saved, including lines that were hidden by filters or mutes.

### Which run is reopened

Each terminal keeps its own last run: `dendros reopen` opens the last TUI launch started **from the same terminal**. Starting a new TUI launch in that terminal replaces it.

Saved runs of terminals that have since been closed are deleted automatically.

A run is only saved if the TUI actually opened. Classic-mode launches and launches whose output was redirected aren't saved.

If there is nothing to reopen, DendROS says so:

<div class="term">
  <div class="term-bar">
    <div class="term-dots">
      <div class="term-dot term-dot-red"></div>
      <div class="term-dot term-dot-yellow"></div>
      <div class="term-dot term-dot-green"></div>
    </div>
    <div class="term-title">dendros reopen</div>
  </div>
  <div class="term-body"><span class="t-blue">[dend</span><span class="t-orange">ROS]</span> no saved TUI run for this terminal</div>
</div>

---

## Notes

- A review never receives commands sent with `dendros focus`, `dendros find` and so on; those always go to a live launch.
- Saved runs live in `~/.config/dendROS/last_run/`.
