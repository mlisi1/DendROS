<p align="center">
  <img src="docs/assets/images/logo_no_bg.png" width="300" alt="DendROS"/>
</p>

<h1 align="center">DendROS</h1>
<p align="center"><em>Color-coded ROS 2 output — because a wall of white text from 32 nodes is nobody's debugging tool.</em></p>

<p align="center">
  <a href="https://github.com/mlisi1/DendROS/actions/workflows/ci.yml"><img src="https://github.com/mlisi1/DendROS/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/github/license/mlisi1/DendROS" alt="License"/></a>
  &nbsp;
  <img src="https://img.shields.io/badge/ROS%202-compatible-22314E" alt="ROS 2 compatible"/>
</p>

<p align="center">
  <a href="https://mlisi1.github.io/DendROS"><strong>📖 Documentation</strong></a>
</p>

<br>




You launched your stack. Nav2, SLAM, hardware drivers, your own nodes — all printing to the same terminal,
all the same color. By the time you find the line you were looking for, it has scrolled past.

**DendROS assigns each group of nodes its own color.** You could have localization in blue, navigation in green,
hardware in orange — defined once in a small YAML file that lives inside your package.
No launch file edits. No new ROS 2 dependencies. Packages without a config pass through completely unchanged.
It also features some quality of life improvements for ROS outputs.




<br clear="right"/>



## Features


- ### **Color by group** 
  One config file per package maps node groups to colors, badges, and display rules

<p align="center">
<img src="docs/assets/images/screenshots/terminal_output.png" width="600" alt="Colored Terminal Output"/>
</p>

- ### **All main `ros2` CLI commands wrapped**
  `ros2 node list`, `ros2 node info`, `ros2 service list`, `ros2 action list`, `ros2 topic list`, `ros2 param list`, and `ros2 param describe` — all colorized with the same group colors and badges, no extra config required. [→ Full feature list](https://mlisi1.github.io/DendROS/node-list/#ros2--intercepted-subcommands)

- ### **One command to get started**
   Too lazy to look up how DendROS config works? We got you covered: `dendros init` scans your launch files and generates an initial config for you

<p align="center">
<img src="docs/assets/images/screenshots/dendros_init.png" width="600" alt="Colored Terminal Output"/>
</p>

- ### **Crash alert** 
  An inline banner flags crashed nodes the moment they die, lists the exit code, and repeats periodically so you don't miss it in fast-scrolling output

<p align="center">
<img src="docs/assets/images/screenshots/crash_alert.png" width="600" alt="Colored Terminal Output"/>
</p>

- ### **Traceback highlighting**
  Python tracebacks are colored automatically: bold red for the header and exception line, dim red for the frames; configurable per session

<p align="center">
<img src="docs/assets/images/screenshots/highlighted_traceback.png" width="600" alt="Colored Terminal Output"/>
</p>

- ### **Keyword highlighting**
  Mark specific words or patterns in bold or in a custom color — per group, or package-wide. 

<p align="center">
<img src="docs/assets/images/screenshots/highlight.png" width="600" alt="Colored Terminal Output"/>
</p>




- ### **Parameter change alert**
  When a node's parameter changes at runtime — via `ros2 param set` or any parameter service client — an inline notification appears in the launch terminal showing the node, parameter name, and old→new value. Two styles: compact inline and a full-width inverted block that's hard to miss in busy logs.

<p align="center">
<img src="docs/assets/images/screenshots/param_alert_inline.png" width="600" alt="param change alert inline"/>
</p>
<p align="center">
<img src="docs/assets/images/screenshots/param_alert_inverted.png" width="600" alt="param change alert inverted"/>
</p>

- ### **Truly non-invasive** 
  Shell-level pipe; you won't loose autocompletion or aliases for launch files

<img
  align="right"
  src="docs/assets/images/dendrobate.png"
  width="140"
  style="transform: scaleX(-1);">

- ### **Works everywhere** 
  Host install, Docker, any ROS 2 distribution

## Install

```bash
git clone https://github.com/mlisi1/DendROS
cd DendROS && bash install.sh && source ~/.bashrc
```

## Quick start
Go to your bringup launch file package (or any package containing launch files) and run ```dendros init``` to generate an initial config file listing the nodes called in the launch file. You can use ```--recursive``` (or ```-r```) to include nodes called by nested launch files. 
```bash
cd ~/ros2_ws/src/my_bringup
dendros init          # scan your launch files → write config/dendROS.yaml
```

Edit the colors in the generated config, then build and launch as usual:

```bash
colcon build --packages-select my_bringup
source install/setup.bash
ros2 launch my_bringup main.launch.py
```

## Global settings

If you want to customize the global configs, `dendros config` opens an interactive TUI to tune defaults across all your packages. Use the arrow keys to navigate or to change the selected option. 

<p align="center">
  <img src="docs/assets/images/screenshots/dendros_config.png" width="780" alt="dendros config TUI"/>
</p>



MIT — see [LICENSE](LICENSE).
