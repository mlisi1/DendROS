"""Tests for dendros_action_list.py colorization."""

import os
import sys
import subprocess

import pytest
import yaml

REPO_ROOT        = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
ACTION_LIST_PATH = os.path.join(REPO_ROOT, 'dendROS', 'dendros_action_list.py')

from conftest import assert_segment_colored, assert_segment_uncolored, colored_segments, strip_ansi


# ── Helper ────────────────────────────────────────────────────────────────────

def run_action_list(tmp_prefix, actions, global_cfg=None, node_colors=None, timeout=10):
    """Run dendros_action_list.py with action paths as stdin; return (stdout, stderr, rc)."""
    env = os.environ.copy()
    env['AMENT_PREFIX_PATH'] = tmp_prefix
    env.pop('ROS_DISTRO', None)
    env['HOME'] = tmp_prefix

    cfg_dir = os.path.join(tmp_prefix, '.config', 'dendROS')
    os.makedirs(cfg_dir, exist_ok=True)

    if global_cfg:
        with open(os.path.join(cfg_dir, 'defaults.yaml'), 'w') as f:
            yaml.dump(global_cfg, f)
    if node_colors:
        with open(os.path.join(cfg_dir, 'node_colors.yaml'), 'w') as f:
            yaml.dump(node_colors, f)

    stdin = '\n'.join(actions) + '\n'
    result = subprocess.run(
        [sys.executable, ACTION_LIST_PATH],
        input=stdin.encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# ── Node color resolution via prefix ─────────────────────────────────────────

class TestActionNodeColor:
    """Actions are colored based on their owning-node path prefix."""

    def test_namespaced_action_colored(self, tmp_path):
        nc = {'color_map': {'bt_navigator': '35'}, 'tag_map': {'bt_navigator': ''},
              'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path),
                                       ['/bt_navigator/navigate_to_pose'], node_colors=nc)
        assert_segment_colored(stdout, '/bt_navigator/navigate_to_pose', '35')

    def test_top_level_action_not_colored(self, tmp_path):
        nc = {'color_map': {'bt_navigator': '35'}, 'tag_map': {'bt_navigator': ''},
              'style_map': {}}
        # Top-level /navigate_to_pose has no node prefix → unmatched
        stdout, _, _ = run_action_list(str(tmp_path), ['/navigate_to_pose'], node_colors=nc)
        assert_segment_uncolored(stdout, '/navigate_to_pose')

    def test_multiple_actions_same_node(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': ''}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path),
                                       ['/robot/spin', '/robot/backup'], node_colors=nc)
        assert_segment_colored(stdout, '/robot/spin', '33')
        assert_segment_colored(stdout, '/robot/backup', '33')

    def test_deep_namespace_matched_by_basename(self, tmp_path):
        nc = {'color_map': {'navigator': '36'}, 'tag_map': {'navigator': ''}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path),
                                       ['/my_ns/navigator/follow_path'], node_colors=nc)
        assert_segment_colored(stdout, '/my_ns/navigator/follow_path', '36')

    def test_wildcard_pattern(self, tmp_path):
        nc = {'color_map': {'nav2_*': '34'}, 'tag_map': {'nav2_*': ''}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path),
                                       ['/nav2_bt_navigator/navigate_to_pose',
                                        '/nav2_controller/follow_path'], node_colors=nc)
        assert_segment_colored(stdout, '/nav2_bt_navigator/navigate_to_pose', '34')
        assert_segment_colored(stdout, '/nav2_controller/follow_path', '34')

    def test_unmatched_prefix_passthrough(self, tmp_path):
        nc = {'color_map': {'known_node': '32'}, 'tag_map': {'known_node': ''}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path), ['/unknown/some_action'], node_colors=nc)
        assert_segment_uncolored(stdout, '/unknown/some_action')

    def test_no_shared_file_passthrough(self, tmp_path):
        stdout, _, _ = run_action_list(str(tmp_path), ['/robot/spin'])
        assert '/robot/spin' in stdout
        assert '\033[' not in stdout

    def test_empty_lines_preserved(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': ''}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path), ['/robot/spin', '', '/other/act'],
                                       node_colors=nc)
        assert '' in stdout.splitlines()


# ── -t flag: type annotation dimmed ──────────────────────────────────────────

class TestActionListTypeFlag:
    """-t flag appends ' [type]'; type content must be rendered dim."""

    def test_type_dimmed_for_matched_action(self, tmp_path):
        nc = {'color_map': {'bt_navigator': '35'}, 'tag_map': {'bt_navigator': ''},
              'style_map': {}}
        line = '/bt_navigator/navigate_to_pose [nav2_msgs/action/NavigateToPose]'
        stdout, _, _ = run_action_list(str(tmp_path), [line], node_colors=nc)
        assert_segment_colored(stdout, '/bt_navigator/navigate_to_pose', '35')
        assert '[\033[2mnav2_msgs/action/NavigateToPose\033[0m]' in stdout

    def test_type_dimmed_for_top_level_action(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        line = '/navigate_to_pose [nav2_msgs/action/NavigateToPose]'
        stdout, _, _ = run_action_list(str(tmp_path), [line], node_colors=nc)
        assert '[\033[2mnav2_msgs/action/NavigateToPose\033[0m]' in stdout

    def test_type_not_colored_with_node_color(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': ''}, 'style_map': {}}
        line = '/robot/spin [nav2_msgs/action/Spin]'
        stdout, _, _ = run_action_list(str(tmp_path), [line], node_colors=nc)
        assert '\033[33mnav2_msgs' not in stdout

    def test_no_type_unchanged(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': ''}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path), ['/robot/spin'], node_colors=nc)
        assert '[' not in strip_ansi(stdout)  # no spurious type bracket in plain text

    def test_tag_plus_type(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': 'ROB'}, 'style_map': {}}
        line = '/robot/spin [nav2_msgs/action/Spin]'
        stdout, _, _ = run_action_list(str(tmp_path), [line], node_colors=nc)
        assert '[ROB]' in stdout
        assert '[\033[2mnav2_msgs/action/Spin\033[0m]' in stdout

    def test_dim_unmatched_with_type(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        line = '/unknown/action [custom_msgs/action/MyAction]'
        stdout, _, _ = run_action_list(str(tmp_path), [line], node_colors=nc,
                                       global_cfg={'dim_unmatched': True})
        assert '\033[2m/unknown/action\033[0m' in stdout
        assert '[\033[2mcustom_msgs/action/MyAction\033[0m]' in stdout


# ── Tag badge (always left / before) ─────────────────────────────────────────

class TestActionListTag:
    """Tag badge appears to the left of the action path."""

    def test_tag_shown_before_action(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': 'ROB'}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path), ['/robot/spin'], node_colors=nc)
        assert '[ROB]' in stdout
        line = [l for l in stdout.splitlines() if '/robot/spin' in l][0]
        assert line.index('[ROB]') < line.index('/robot/spin')

    def test_tag_hidden_when_show_tag_cli_false(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': 'ROB'}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path), ['/robot/spin'],
                                       node_colors=nc,
                                       global_cfg={'show_tag_cli': False})
        assert '[ROB]' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        nc = {'color_map': {'robot': '33'}, 'tag_map': {'robot': 'ROB'},
              'style_map': {'robot': 'inverted'}}
        stdout, _, _ = run_action_list(str(tmp_path), ['/robot/spin'], node_colors=nc)
        assert '\033[33;7m[ROB]' in stdout

    def test_unmatched_tag(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_action_list(
            str(tmp_path), ['/unknown/spin'], node_colors=nc,
            global_cfg={'unmatched_color': 'white', 'unmatched_tag': '?'})
        assert '[?]' in stdout


# ── Unmatched / dim_unmatched ─────────────────────────────────────────────────

class TestActionListUnmatched:

    def test_unmatched_color_applied(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_action_list(
            str(tmp_path), ['/unknown/some_action'], node_colors=nc,
            global_cfg={'unmatched_color': 'cyan'})
        assert '\033[' in stdout

    def test_dim_unmatched(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_action_list(
            str(tmp_path), ['/unknown/some_action'], node_colors=nc,
            global_cfg={'dim_unmatched': True})
        assert f'\033[2m/unknown/some_action\033[0m' in stdout

    def test_passthrough_when_no_config(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_action_list(str(tmp_path), ['/unknown/some_action'], node_colors=nc)
        assert_segment_uncolored(stdout, '/unknown/some_action')


# ── AMENT_PREFIX_PATH fallback ────────────────────────────────────────────────

class TestActionListFallback:

    def test_fallback_scan_colors_action(self, tmp_path):
        cfg_dir = tmp_path / 'share' / 'my_pkg' / 'config'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'dendROS.yaml').write_text(yaml.dump({
            'groups': {'nav': {'color': 'bold blue', 'label': 'NAV',
                               'nodes': ['bt_navigator']}}
        }))
        stdout, _, _ = run_action_list(str(tmp_path),
                                       ['/bt_navigator/navigate_to_pose'])
        assert '\033[' in stdout
