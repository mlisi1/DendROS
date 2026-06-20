"""Tests for dendros_node_list.py colorization."""

import os
import sys
import subprocess

import pytest
import yaml

REPO_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
NODE_LIST_PATH = os.path.join(REPO_ROOT, 'dendROS', 'dendros_node_list.py')
PIPE_PATH      = os.path.join(REPO_ROOT, 'dendROS', 'dendROS_pipe.py')

from conftest import assert_segment_colored, assert_segment_uncolored


# ── Helper ────────────────────────────────────────────────────────────────────

def run_node_list(tmp_prefix, nodes, global_cfg=None, node_colors=None, timeout=10):
    """Run dendros_node_list.py with node paths as stdin; return (stdout, stderr, rc).

    node_colors  — dict with keys color_map/tag_map/style_map written as the shared file
                   (simulates what the pipe writes on ros2 launch/run).
    global_cfg   — dict written as defaults.yaml.
    """
    env = os.environ.copy()
    env['AMENT_PREFIX_PATH'] = tmp_prefix
    env.pop('ROS_DISTRO', None)
    env['HOME'] = tmp_prefix  # isolate from real ~/.config/dendROS/

    cfg_dir = os.path.join(tmp_prefix, '.config', 'dendROS')
    os.makedirs(cfg_dir, exist_ok=True)

    if global_cfg:
        with open(os.path.join(cfg_dir, 'defaults.yaml'), 'w') as f:
            yaml.dump(global_cfg, f)
    if node_colors:
        with open(os.path.join(cfg_dir, 'node_colors.yaml'), 'w') as f:
            yaml.dump(node_colors, f)

    stdin = '\n'.join(nodes) + '\n'
    result = subprocess.run(
        [sys.executable, NODE_LIST_PATH],
        input=stdin.encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


def run_pipe(prefix, pkg, lines, home=None, timeout=10):
    """Run dendROS_pipe.py simulating ros2 launch; return (stdout, stderr, rc)."""
    env = os.environ.copy()
    env['AMENT_PREFIX_PATH'] = prefix
    env['HOME'] = home or prefix
    env.pop('ROS_DISTRO', None)
    result = subprocess.run(
        [sys.executable, PIPE_PATH, 'launch', pkg],
        input=''.join(lines).encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# ── Primary path: shared node_colors.yaml ─────────────────────────────────────

class TestNodeListSharedFile:
    """Verify colorization via the shared file written by the pipe."""

    def test_matched_node_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'], node_colors=nc)
        assert_segment_colored(stdout, '/talker', '34;1')

    def test_unmatched_node_passthrough(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': None}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/unknown'], node_colors=nc)
        assert_segment_uncolored(stdout, '/unknown')

    def test_namespace_matched_by_basename(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/my_ns/talker'], node_colors=nc)
        assert_segment_colored(stdout, '/my_ns/talker', '32')

    def test_multiple_nodes(self, tmp_path):
        nc = {
            'color_map': {'node_a': '31', 'node_b': '32'},
            'tag_map':   {'node_a': '',   'node_b': ''},
            'style_map': {},
        }
        stdout, _, _ = run_node_list(str(tmp_path), ['/node_a', '/node_b', '/unknown'],
                                     node_colors=nc)
        assert_segment_colored(stdout, '/node_a', '31')
        assert_segment_colored(stdout, '/node_b', '32')
        assert_segment_uncolored(stdout, '/unknown')

    def test_wildcard_pattern(self, tmp_path):
        nc = {'color_map': {'nav2_*': '36'}, 'tag_map': {'nav2_*': 'N2'}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/nav2_controller', '/nav2_planner'],
                                     node_colors=nc)
        assert_segment_colored(stdout, '/nav2_controller', '36')
        assert_segment_colored(stdout, '/nav2_planner', '36')

    def test_empty_lines_preserved(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker', '', '/other'], node_colors=nc)
        assert '' in stdout.splitlines()

    def test_no_shared_file_passthrough(self, tmp_path):
        stdout, _, _ = run_node_list(str(tmp_path), ['/some_node'])
        assert '/some_node' in stdout
        assert '\033[' not in stdout


# ── Cross-terminal: pipe writes, node list reads ──────────────────────────────

class TestCrossTerminal:
    """End-to-end: pipe run in Terminal A writes colors; node list in Terminal B reads them."""

    def test_pipe_writes_node_colors_file(self, make_ament_tree, tmp_path):
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'nav': {'color': 'bold blue', 'label': 'NAV', 'nodes': ['talker']}}
        })
        run_pipe(prefix, pkg, ['[talker-1] [INFO] hello\n'])

        nc_path = os.path.join(prefix, '.config', 'dendROS', 'node_colors.yaml')
        assert os.path.isfile(nc_path), 'node_colors.yaml was not written by the pipe'
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        assert 'talker' in data.get('color_map', {})
        assert data['tag_map']['talker'] == 'NAV'

    def test_node_list_reads_pipe_output(self, make_ament_tree, tmp_path):
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'nav': {'color': 'bold blue', 'label': 'NAV', 'nodes': ['talker']}}
        })
        # Terminal A: pipe writes node_colors.yaml
        run_pipe(prefix, pkg, ['[talker-1] [INFO] hello\n'])

        # Terminal B: node list with same HOME, AMENT_PREFIX_PATH cleared (different terminal)
        env = os.environ.copy()
        env['HOME'] = prefix
        env['AMENT_PREFIX_PATH'] = ''
        env.pop('ROS_DISTRO', None)
        result = subprocess.run(
            [sys.executable, NODE_LIST_PATH],
            input=b'/talker\n',
            capture_output=True, env=env, timeout=10,
        )
        assert_segment_colored(result.stdout.decode(), '/talker', '34;1')

    def test_last_launch_overwrites_file(self, make_ament_tree, tmp_path):
        # _save_node_colors no longer merges with the existing file — it always
        # writes the current in-memory maps.  Sequential launches therefore reset
        # node_colors.yaml to the current config, eliminating stale entries from
        # a previous config.  The last launch's data is what ros2 node list sees.
        prefix_a, pkg_a = make_ament_tree('pkg_a', {
            'groups': {'a': {'color': 'red', 'nodes': ['node_a']}}
        })
        prefix_b = str(tmp_path / 'prefix_b')
        cfg_b_dir = os.path.join(prefix_b, 'share', 'pkg_b', 'config')
        os.makedirs(cfg_b_dir)
        with open(os.path.join(cfg_b_dir, 'dendROS.yaml'), 'w') as f:
            yaml.dump({'groups': {'b': {'color': 'green', 'nodes': ['node_b']}}}, f)

        shared_home = str(tmp_path / 'home')
        os.makedirs(shared_home, exist_ok=True)

        run_pipe(prefix_a, pkg_a, ['[node_a-1] [INFO] hello\n'], home=shared_home)
        run_pipe(prefix_b, 'pkg_b', ['[node_b-1] [INFO] hello\n'], home=shared_home)

        # After pkg_b launches, only pkg_b's data is in node_colors.yaml
        nc_path = os.path.join(shared_home, '.config', 'dendROS', 'node_colors.yaml')
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        assert 'node_b' in data.get('color_map', {}), 'last launch must be in file'
        assert 'node_a' not in data.get('color_map', {}), \
            'previous launch data must not survive into the new launch file'

    def test_stale_config_data_cleared_on_new_launch(self, make_ament_tree, tmp_path):
        # Regression: old config had LOC labels; user deleted it and created a new
        # config with dendros init (no labels, all blue).  The old node_colors.yaml
        # must not bleed its LOC tag into the new launch run.
        from lib.colors import _resolve_color
        shared_home = str(tmp_path / 'home')
        os.makedirs(shared_home, exist_ok=True)

        # Simulate an old config run that wrote LOC tags into node_colors.yaml
        old_color = _resolve_color('bold blue')
        nc_dir = os.path.join(shared_home, '.config', 'dendROS')
        os.makedirs(nc_dir, exist_ok=True)
        with open(os.path.join(nc_dir, 'node_colors.yaml'), 'w') as f:
            yaml.dump({
                'color_map': {'slam_node': old_color, 'slam_toolbox': old_color},
                'tag_map':   {'slam_node': 'LOC', 'slam_toolbox': 'LOC'},
                'style_map': {},
            }, f)

        # New config: slam_node in a group with no label, same blue but different intent
        prefix, pkg = make_ament_tree('new_pkg', {
            'groups': {'all': {'color': 'bold blue', 'label': '', 'nodes': ['slam_node']}}
        })

        # Run the pipe — it must overwrite node_colors.yaml with the new config
        run_pipe(prefix, pkg, ['[slam_node-1] [INFO] [1.0] [t]: hello\n'], home=shared_home)

        with open(os.path.join(nc_dir, 'node_colors.yaml')) as f:
            data = yaml.safe_load(f)
        assert data.get('tag_map', {}).get('slam_node') != 'LOC', \
            'LOC tag from old config must be cleared by new launch'


# ── Logger discovery: process name → ROS node name ───────────────────────────

class TestLoggerDiscovery:
    """The pipe dynamically maps logger names (ROS node names) to the same color
    as their process name, bridging the gap between launch output and ros2 node list."""

    def test_pipe_discovers_ros_node_name(self, make_ament_tree, tmp_path):
        """slam_node (process) → slam_toolbox (ROS/logger) discovered and written."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['slam_node']}}
        })
        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: SlamToolbox started\n'
        run_pipe(prefix, pkg, [line])

        nc_path = os.path.join(prefix, '.config', 'dendROS', 'node_colors.yaml')
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        cm = data['color_map']
        assert 'slam_node' in cm, 'process name must be in color_map'
        assert 'slam_toolbox' in cm, 'ROS node name must be discovered and written'
        assert cm['slam_toolbox'] == cm['slam_node'], 'same color as process name'

    def test_discovered_name_colorizes_node_list(self, make_ament_tree, tmp_path):
        """After pipe runs, ros2 node list can colorize /slam_toolbox even though the
        config only mentions slam_node."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['slam_node']}}
        })
        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: SlamToolbox started\n'
        run_pipe(prefix, pkg, [line])

        # Node list in a different terminal (AMENT_PREFIX_PATH cleared)
        env = os.environ.copy()
        env['HOME'] = prefix
        env['AMENT_PREFIX_PATH'] = ''
        env.pop('ROS_DISTRO', None)
        result = subprocess.run(
            [sys.executable, NODE_LIST_PATH],
            input=b'/slam_toolbox\n',
            capture_output=True, env=env, timeout=10,
        )
        assert_segment_colored(result.stdout.decode(), '/slam_toolbox', '34;1')

    def test_tag_inherited_by_discovered_name(self, make_ament_tree, tmp_path):
        """Discovered logger entry inherits the same label as the process name."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['slam_node']}}
        })
        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: msg\n'
        run_pipe(prefix, pkg, [line])

        nc_path = os.path.join(prefix, '.config', 'dendROS', 'node_colors.yaml')
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        assert data['tag_map'].get('slam_toolbox') == 'LOC'

    def test_same_name_not_duplicated(self, make_ament_tree, tmp_path):
        """When logger name == process name, no extra entry is added."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'nav': {'color': 'bold green', 'nodes': ['bt_navigator']}}
        })
        # logger matches process name (the common case)
        line = '[bt_navigator-3] [INFO] [1781949092.587] [bt_navigator]: ready\n'
        run_pipe(prefix, pkg, [line])

        nc_path = os.path.join(prefix, '.config', 'dendROS', 'node_colors.yaml')
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        keys = list(data['color_map'].keys())
        assert keys.count('bt_navigator') == 1, 'no duplicate entry expected'

    def test_existing_entry_not_overwritten(self, make_ament_tree, tmp_path):
        """A logger name already in the config is never overwritten by discovery."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {
                'a': {'color': 'red',  'nodes': ['slam_node']},
                'b': {'color': 'green', 'nodes': ['slam_toolbox']},  # explicit entry
            }
        })
        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: msg\n'
        run_pipe(prefix, pkg, [line])

        nc_path = os.path.join(prefix, '.config', 'dendROS', 'node_colors.yaml')
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        # slam_toolbox was explicitly green; discovery must not change it to red
        from lib.colors import _resolve_color
        assert data['color_map']['slam_toolbox'] == _resolve_color('green'), \
            'explicitly configured entry must win over discovery'

    def test_tag_propagated_to_pre_coloured_logger(self, make_ament_tree):
        """Regression: a logger name already in the shared file without a tag (e.g.
        written by a previous launch that had no labels) must receive the tag once
        the current launch's config has one for its process name."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['slam_node']}}
        })
        # Pre-populate shared file as if a previous tagless launch ran
        nc_path = os.path.join(prefix, '.config', 'dendROS')
        os.makedirs(nc_path, exist_ok=True)
        from lib.colors import _resolve_color
        loc_code = _resolve_color('bold blue')
        with open(os.path.join(nc_path, 'node_colors.yaml'), 'w') as f:
            yaml.dump({
                'color_map': {'slam_toolbox': loc_code},
                'tag_map':   {'slam_toolbox': None},  # pre-populated with null — the real failure mode
                'style_map': {},
            }, f)

        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: msg\n'
        run_pipe(prefix, pkg, [line], home=prefix)

        with open(os.path.join(nc_path, 'node_colors.yaml')) as f:
            data = yaml.safe_load(f)
        assert data.get('tag_map', {}).get('slam_toolbox') == 'LOC', \
            'tag must be propagated to pre-coloured logger entry'


class TestReverseLoggerDiscovery:
    """Config has ROS node name (slam_toolbox); launch output uses process name (slam_node).
    The pipe must colorize the launch output by reversing the logger lookup."""

    def test_launch_line_colored_via_logger_reverse(self, make_ament_tree):
        """When config has slam_toolbox but launch says [slam_node-2], the line is colored."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['slam_toolbox']}}
        })
        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: SlamToolbox started\n'
        out, _, _ = run_pipe(prefix, pkg, [line])
        assert_segment_colored(out, '[slam_node-2]', '34;1')

    def test_process_name_added_to_shared_file(self, make_ament_tree):
        """After reverse discovery, slam_node is written to node_colors.yaml."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['slam_toolbox']}}
        })
        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: msg\n'
        run_pipe(prefix, pkg, [line])

        nc_path = os.path.join(prefix, '.config', 'dendROS', 'node_colors.yaml')
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        cm = data['color_map']
        assert 'slam_toolbox' in cm, 'original entry preserved'
        assert 'slam_node' in cm, 'process name discovered and written'
        assert cm['slam_node'] == cm['slam_toolbox'], 'same color as ROS node name'

    def test_tag_inherited_by_process_name(self, make_ament_tree):
        """slam_node inherits the label from slam_toolbox's group."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['slam_toolbox']}}
        })
        line = '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: msg\n'
        run_pipe(prefix, pkg, [line])

        nc_path = os.path.join(prefix, '.config', 'dendROS', 'node_colors.yaml')
        with open(nc_path) as f:
            data = yaml.safe_load(f)
        assert data['tag_map'].get('slam_node') == 'LOC'

    def test_both_amcl_cases(self, make_ament_tree):
        """amcl (config) ↔ amcl_node (process): both directions work together."""
        prefix, pkg = make_ament_tree('my_pkg', {
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC',
                               'nodes': ['slam_toolbox', 'amcl']}}
        })
        lines = [
            '[slam_node-2] [INFO] [1781949092.587] [slam_toolbox]: started\n',
            '[amcl_node-1] [INFO] [1781949092.600] [amcl]: initialized\n',
        ]
        out, _, _ = run_pipe(prefix, pkg, lines)
        assert_segment_colored(out, '[slam_node-2]', '34;1')
        assert_segment_colored(out, '[amcl_node-1]', '34;1')


# ── Tag badge (via shared file) ───────────────────────────────────────────────

class TestNodeListTag:
    def test_tag_after_position(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'],
                                     global_cfg={'tag_position': 'after'}, node_colors=nc)
        assert stdout.index('/talker') < stdout.index('[NAV]')

    def test_tag_before_position(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'],
                                     global_cfg={'tag_position': 'before'}, node_colors=nc)
        assert stdout.index('[NAV]') < stdout.index('/talker')

    def test_no_tag_when_show_group_tag_false(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'],
                                     global_cfg={'show_group_tag': False}, node_colors=nc)
        assert '[NAV]' not in stdout

    def test_no_tag_when_label_empty(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'], node_colors=nc)
        assert '[]' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'],
                                     global_cfg={'tag_style': 'inverted'}, node_colors=nc)
        assert ';7m[NAV]' in stdout

    def test_per_node_inverted_style(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'},
              'style_map': {'talker': 'inverted'}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'], node_colors=nc)
        assert ';7m[NAV]' in stdout

    def test_none_label_suppresses_tag(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': None}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/talker'], node_colors=nc)
        assert '[' not in stdout.replace('\033[', '')


# ── Unmatched node handling ───────────────────────────────────────────────────

class TestNodeListUnmatched:
    def test_unmatched_color(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/unknown'],
                                     global_cfg={'unmatched_color': 'red'}, node_colors=nc)
        assert_segment_colored(stdout, '/unknown', '31')

    def test_dim_unmatched(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/unknown'],
                                     global_cfg={'dim_unmatched': True}, node_colors=nc)
        assert '\033[2m/unknown\033[0m' in stdout

    def test_unmatched_tag(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/unknown'],
                                     global_cfg={'unmatched_color': 'red', 'unmatched_tag': '?'},
                                     node_colors=nc)
        assert '[?]' in stdout
        assert_segment_colored(stdout, '/unknown', '31')

    def test_unmatched_no_tag_without_color(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_list(str(tmp_path), ['/unknown'],
                                     global_cfg={'unmatched_tag': '?'}, node_colors=nc)
        assert '[?]' not in stdout
        assert_segment_uncolored(stdout, '/unknown')


# ── Fallback: AMENT_PREFIX_PATH scan when no shared file exists ───────────────

class TestNodeListFallback:
    def test_fallback_to_ament_scan(self, make_ament_tree):
        prefix, _ = make_ament_tree('my_pkg', {
            'groups': {'nav': {'color': 'bold blue', 'nodes': ['talker']}}
        })
        # No node_colors.yaml → falls back to AMENT_PREFIX_PATH scan
        stdout, _, _ = run_node_list(prefix, ['/talker'])
        assert_segment_colored(stdout, '/talker', '34;1')

    def test_fallback_passthrough_when_empty(self, tmp_path):
        stdout, _, _ = run_node_list(str(tmp_path), ['/some_node'])
        assert '/some_node' in stdout
        assert '\033[' not in stdout
