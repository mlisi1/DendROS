# Installation

## Requirements

- ROS 2 (any distribution)
- Python 3.8+
- `pyyaml` (`pip3 install pyyaml`)
- bash shell

---

## Host install

```bash
git clone https://github.com/mlisi1/DendROS
cd DendROS
bash install.sh
source ~/.bashrc
```

The installer copies files to `/usr/local/dendROS/` and adds a `source` line to `~/.bashrc`.
From that point on, `ros2 launch` and `ros2 run` are automatically piped through the colorizer.

### Uninstall

```bash
bash uninstall.sh
```

Removes the install directory and the `.bashrc` lines cleanly.

---

## Docker

### Option A — copy files directly

Add this snippet to your `Dockerfile` after your ROS 2 base setup:

```dockerfile
COPY dendROS/ /usr/local/dendROS/
RUN pip3 install --no-cache-dir pyyaml \
 && chmod +x /usr/local/dendROS/dendROS_pipe.py \
 && printf '\n# dendROS\nsource /usr/local/dendROS/dendROS.sh\n' >> /root/.bashrc
```

### Option B — non-interactive installer

```dockerfile
COPY . /tmp/dendROS/
RUN bash /tmp/dendROS/install.sh -y
```

The `-y` flag skips interactive prompts for use in `RUN` layers.

### docker-compose

Add these settings to your service so colors render correctly:

```yaml
services:
  my_robot:
    tty: true
    stdin_open: true
    environment:
      - RCUTILS_COLORIZED_OUTPUT=1
```

!!! note
    `docker compose exec my_robot bash` sources `~/.bashrc` automatically.
    `docker compose up` log streaming has no TTY — `tty: true` is required for colors to render there.

---

## Verification

After sourcing `.bashrc`, run any launch command. If DendROS is active you should see colored output. To confirm it found your config:

```bash
DENDROS_DEBUG=1 ros2 launch my_pkg my_launch.py
```

This prints a config summary to stderr before processing starts. See [Reference](reference.md#environment-variables) for details.
