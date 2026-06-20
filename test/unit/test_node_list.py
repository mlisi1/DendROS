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

    def test_multiple_launches_merge(self, make_ament_tree, tmp_path):
        prefix_a, pkg_a = make_ament_tree('pkg_a', {
            'groups': {'a': {'color': 'red', 'nodes': ['node_a']}}
        })
        # Second package in a separate prefix directory
        prefix_b = str(tmp_path / 'prefix_b')
        cfg_b_dir = os.path.join(prefix_b, 'share', 'pkg_b', 'config')
        os.makedirs(cfg_b_dir)
        with open(os.path.join(cfg_b_dir, 'dendROS.yaml'), 'w') as f:
            yaml.dump({'groups': {'b': {'color': 'green', 'nodes': ['node_b']}}}, f)

        shared_home = str(tmp_path / 'home')
        os.makedirs(shared_home, exist_ok=True)

        # Two separate launches, both writing to the same shared HOME
        run_pipe(prefix_a, pkg_a, ['[node_a-1] [INFO] hello\n'], home=shared_home)
        run_pipe(prefix_b, 'pkg_b', ['[node_b-1] [INFO] hello\n'], home=shared_home)

        # Node list sees colors from both launches
        env = os.environ.copy()
        env['HOME'] = shared_home
        env['AMENT_PREFIX_PATH'] = ''
        env.pop('ROS_DISTRO', None)
        result = subprocess.run(
            [sys.executable, NODE_LIST_PATH],
            input=b'/node_a\n/node_b\n',
            capture_output=True, env=env, timeout=10,
        )
        stdout = result.stdout.decode()
        assert_segment_colored(stdout, '/node_a', '31')
        assert_segment_colored(stdout, '/node_b', '32')


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
