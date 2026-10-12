# Installation

## Requirements

- ROS 2 (any distribution)
- Python 3.8+
- `pyyaml` — `pip3 install pyyaml`
- bash shell

---

## Install

=== "Host"

    ```bash
    git clone https://github.com/mlisi1/DendROS
    cd DendROS
    bash install.sh
    source ~/.bashrc
    ```

    The installer copies files to `/usr/local/dendROS/` and adds a `source` line to `~/.bashrc`.
    From that point on, `ros2 launch` and `ros2 run` are automatically piped through the colorizer.

=== "Docker — installer"

    Use the non-interactive `-y` flag for `RUN` layers:

    ```dockerfile
    COPY . /tmp/dendROS/
    RUN bash /tmp/dendROS/install.sh -y
    ```

=== "Docker — manual"

    Copy only the essential runtime files:

    ```dockerfile
    COPY dendROS/ /usr/local/dendROS/
    RUN pip3 install --no-cache-dir pyyaml \
     && chmod +x /usr/local/dendROS/dendROS_pipe.py \
     && printf '\n# dendROS\nsource /usr/local/dendROS/dendROS.sh\n' \
        >> /root/.bashrc
    ```

---

## Docker Compose

Add these settings to your service so colors render correctly:

```yaml
services:
  my_robot:
    tty: true
    stdin_open: true
    environment:
      - RCUTILS_COLORIZED_OUTPUT=1
```

!!! tip "Exec vs Up"
    `docker compose exec my_robot bash` sources `~/.bashrc` immediately.
    `docker compose up` log streaming has no TTY — `tty: true` is required for ANSI colors to render there.

---

## Uninstall

```bash
bash uninstall.sh
```

Removes `/usr/local/dendROS/`, the two lines the installer added to `.bashrc`, and DendROS's runtime files in `~/.config/dendROS/` (saved TUI runs, the color cache). Your settings in `~/.config/dendROS/defaults.yaml` are kept, so a reinstall picks them up; delete that folder to remove them too. Open a new terminal afterwards: shells that are already open still have the `ros2` wrapper loaded.

---

## Verify

After sourcing `.bashrc`, run any launch. The ROS 2 demo nodes work well for this:

```bash
ros2 launch demo_nodes_cpp talker_listener_launch.py
```

<div class="term">
  <div class="term-bar">
    <div class="term-dots">
      <div class="term-dot term-dot-red"></div>
      <div class="term-dot term-dot-yellow"></div>
      <div class="term-dot term-dot-green"></div>
    </div>
    <div class="term-title">ros2 launch demo_nodes_cpp talker_listener_launch.py</div>
  </div>
  <div class="term-body-image">
  <p align="center">
<img src="../assets/images/screenshots/verify_tui.png" width="900" alt="A launch opening in the DendROS viewer on a fresh install"/>
</p>
</div>
</div>

If the launch opens in the full-screen viewer with `[dendROS]` and the version in the header, DendROS is active. Press ++ctrl+c++ to stop the launch and ++q++ to close the viewer.

This package has no `dendROS.yaml` yet, so its lines aren't colored. Continue with the [Quick Start](quickstart.md) to create a config for your own package.

To check which config DendROS finds for a package, use [debug output](runtime-control.md#debug-output-dendros_debug):

```bash
DENDROS_DEBUG=1 ros2 launch my_bringup main.launch.py | cat
```

If a package that does have a `dendROS.yaml` still reports `passthrough mode`, its config was not found. Check that:

- The package was built and `install/setup.bash` was sourced.
- `config/dendROS.yaml` is installed to `share/my_bringup/config/` — verify your `CMakeLists.txt` installs the `config/` directory.
