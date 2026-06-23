"""Tests for dendros_node_info.py colorization."""

import json
import os
import sys
import subprocess

import pytest
import yaml

REPO_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
NODE_INFO_PATH = os.path.join(REPO_ROOT, 'dendROS', 'dendros_node_info.py')

from conftest import assert_segment_colored, assert_segment_uncolored

SAMPLE_INFO = """\
/talker
  Subscribers:
    /parameter_events: rcl_interfaces/msg/ParameterEvent
  Publishers:
    /chatter: std_msgs/msg/String
    /rosout: rcl_interfaces/msg/Log
  Service Servers:
    /talker/describe_parameters: rcl_interfaces/srv/DescribeParameters
    /talker/set_parameters: rcl_interfaces/srv/SetParameters
  Service Clients:
    (None)
  Action Servers:
    /count_until: example_interfaces/action/Fibonacci
  Action Clients:
    (None)
"""


def run_node_info(tmp_prefix, stdin_text, global_cfg=None, node_colors=None,
                  topic_publishers=None, timeout=10):
    """Run dendros_node_info.py with stdin_text; return (stdout, stderr, rc).

    topic_publishers — dict {topic: [node_basename, ...]} injected via
                       DENDROS_TOPIC_PUBLISHERS to avoid live graph queries.
                       Pass None to skip graph lookup (defaults to empty).
    """
    env = os.environ.copy()
    env['AMENT_PREFIX_PATH'] = tmp_prefix
    env.pop('ROS_DISTRO', None)
    env['HOME'] = tmp_prefix

    # Always inject the override so tests never hit the live ROS 2 graph.
    # Pass an explicit dict to test subscriber coloring.
    env['DENDROS_TOPIC_PUBLISHERS'] = json.dumps(topic_publishers or {})

    cfg_dir = os.path.join(tmp_prefix, '.config', 'dendROS')
    os.makedirs(cfg_dir, exist_ok=True)

    if global_cfg:
        with open(os.path.join(cfg_dir, 'defaults.yaml'), 'w') as f:
            yaml.dump(global_cfg, f)
    if node_colors:
        with open(os.path.join(cfg_dir, 'node_colors.yaml'), 'w') as f:
            yaml.dump(node_colors, f)

    result = subprocess.run(
        [sys.executable, NODE_INFO_PATH],
        input=stdin_text.encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# ── Node name line ─────────────────────────────────────────────────────────────

class TestNodeInfoNodeName:
    def test_matched_node_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_colored(stdout, '/talker', '34;1')

    def test_tag_after_position(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'tag_position': 'after'}, node_colors=nc)
        assert stdout.index('/talker') < stdout.index('[NAV]')

    def test_tag_before_position(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'tag_position': 'before'}, node_colors=nc)
        assert stdout.index('[NAV]') < stdout.index('/talker')

    def test_no_tag_when_show_group_tag_false(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'show_group_tag': False}, node_colors=nc)
        assert '[NAV]' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'tag_style': 'inverted'}, node_colors=nc)
        assert ';7m[NAV]' in stdout

    def test_unmatched_node_passthrough(self, tmp_path):
        nc = {'color_map': {'other': '34;1'}, 'tag_map': {'other': 'X'}, 'style_map': {}}
        info = '/unknown_node\n  Publishers:\n    /chatter: std_msgs/msg/String\n'
        stdout, _, _ = run_node_info(str(tmp_path), info, node_colors=nc)
        assert_segment_uncolored(stdout, '/unknown_node')

    def test_unmatched_color_applied(self, tmp_path):
        nc = {'color_map': {'other': '34;1'}, 'tag_map': {'other': 'X'}, 'style_map': {}}
        info = '/unknown_node\n  Publishers:\n    /chatter: std_msgs/msg/String\n'
        stdout, _, _ = run_node_info(str(tmp_path), info,
                                     global_cfg={'unmatched_color': 'red'}, node_colors=nc)
        assert_segment_colored(stdout, '/unknown_node', '31')

    def test_namespace_matched_by_basename(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        info = '/my_ns/talker\n  Publishers:\n    /chatter: std_msgs/msg/String\n'
        stdout, _, _ = run_node_info(str(tmp_path), info, node_colors=nc)
        assert_segment_colored(stdout, '/my_ns/talker', '34;1')

    def test_no_config_passthrough(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '/talker' in stdout
        first_line = stdout.splitlines()[0]
        assert '\033[' not in first_line


# ── Section headers ────────────────────────────────────────────────────────────

class TestNodeInfoSectionHeaders:
    def test_publishers_bold(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[1m  Publishers:\033[0m' in stdout

    def test_subscribers_bold(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[1m  Subscribers:\033[0m' in stdout

    def test_service_servers_bold(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[1m  Service Servers:\033[0m' in stdout

    def test_service_clients_bold(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[1m  Service Clients:\033[0m' in stdout

    def test_action_servers_bold(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[1m  Action Servers:\033[0m' in stdout

    def test_action_clients_bold(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[1m  Action Clients:\033[0m' in stdout

    def test_headers_bold_without_config(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '\033[1m  Publishers:\033[0m' in stdout


# ── Output sections (node's own color) ────────────────────────────────────────

class TestNodeInfoOutputSections:
    def test_publisher_entry_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_colored(stdout, '/chatter', '34;1')

    def test_publisher_second_entry_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_colored(stdout, '/rosout', '34;1')

    def test_service_server_entry_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_colored(stdout, '/talker/describe_parameters', '34;1')

    def test_service_server_second_entry_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_colored(stdout, '/talker/set_parameters', '34;1')

    def test_action_server_entry_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_colored(stdout, '/count_until', '34;1')

    def test_output_entries_have_no_tag(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        lines = stdout.splitlines()
        tag_lines = [l for l in lines if '[NAV]' in l]
        # [NAV] badge only on the node name line, never on entry lines
        assert len(tag_lines) == 1
        assert '/talker' in tag_lines[0] and '/chatter' not in tag_lines[0]

    def test_none_entry_not_node_colored(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        for line in stdout.splitlines():
            if '(None)' in line:
                assert '\033[34;1m(None)' not in line

    def test_output_sections_unaffected_when_unmatched(self, tmp_path):
        nc = {'color_map': {'other': '34;1'}, 'tag_map': {'other': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_uncolored(stdout, '/chatter')
        assert_segment_uncolored(stdout, '/talker/describe_parameters')


# ── Input sections (publisher's color) ────────────────────────────────────────

class TestNodeInfoInputSections:
    def test_subscriber_colored_by_publisher(self, tmp_path):
        nc = {
            'color_map': {'talker': '34;1', 'parameter_events_pub': '36'},
            'tag_map':   {'talker': 'NAV',   'parameter_events_pub': 'PE'},
            'style_map': {},
        }
        tp = {'/parameter_events': ['parameter_events_pub']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/parameter_events', '36')

    def test_subscriber_uses_publisher_color_not_own(self, tmp_path):
        """Subscriber entry color comes from the publisher, not from /talker."""
        nc = {
            'color_map': {'talker': '34;1', 'other_node': '32'},
            'tag_map':   {'talker': 'T',     'other_node': 'O'},
            'style_map': {},
        }
        tp = {'/parameter_events': ['other_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/parameter_events', '32')  # other_node's color

    def test_subscriber_no_tag(self, tmp_path):
        """Subscriber entries never show a tag badge."""
        nc = {
            'color_map': {'talker': '34;1', 'pub_node': '32'},
            'tag_map':   {'talker': 'T',     'pub_node': 'PUB'},
            'style_map': {},
        }
        tp = {'/parameter_events': ['pub_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        sub_line = next(l for l in stdout.splitlines() if '/parameter_events' in l)
        assert '[PUB]' not in sub_line

    def test_subscriber_uncolored_when_publisher_unknown(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        # publisher not in color_map → no color
        tp = {'/parameter_events': ['unknown_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_uncolored(stdout, '/parameter_events')

    def test_subscriber_uncolored_when_no_publisher(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        tp = {'/parameter_events': []}  # no publishers for this topic
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_uncolored(stdout, '/parameter_events')

    def test_subscriber_uncolored_with_empty_map(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': 'NAV'}, 'style_map': {}}
        # No topic_publishers injected → empty dict → no graph query
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_uncolored(stdout, '/parameter_events')

    def test_multiple_subscribers_independently_colored(self, tmp_path):
        info = (
            '/my_node\n'
            '  Subscribers:\n'
            '    /scan: sensor_msgs/msg/LaserScan\n'
            '    /imu: sensor_msgs/msg/Imu\n'
            '  Publishers:\n'
            '    /cmd_vel: geometry_msgs/msg/Twist\n'
        )
        nc = {
            'color_map': {'my_node': '33', 'lidar': '36', 'imu_node': '35'},
            'tag_map':   {'my_node': 'M',   'lidar': 'L',  'imu_node': 'I'},
            'style_map': {},
        }
        tp = {'/scan': ['lidar'], '/imu': ['imu_node']}
        stdout, _, _ = run_node_info(str(tmp_path), info, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/scan', '36')   # lidar's color
        assert_segment_colored(stdout, '/imu',  '35')   # imu_node's color
        assert_segment_colored(stdout, '/cmd_vel', '33')  # own color (Publisher)


# ── Type annotation dimming ────────────────────────────────────────────────────

class TestNodeInfoTypeDimming:
    def test_service_server_type_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[2mrcl_interfaces/srv/DescribeParameters\033[0m' in stdout

    def test_publisher_type_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[2mstd_msgs/msg/String\033[0m' in stdout

    def test_action_server_type_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[2mexample_interfaces/action/Fibonacci\033[0m' in stdout

    def test_types_dimmed_without_config(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '\033[2mstd_msgs/msg/String\033[0m' in stdout

    def test_none_entry_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '34;1'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert '\033[2m(None)\033[0m' in stdout

    def test_subscriber_type_dimmed_when_colored(self, tmp_path):
        nc = {
            'color_map': {'talker': '34;1', 'pub': '32'},
            'tag_map':   {'talker': '',      'pub': ''},
            'style_map': {},
        }
        tp = {'/parameter_events': ['pub']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert '\033[2mrcl_interfaces/msg/ParameterEvent\033[0m' in stdout


# ── Fallback: AMENT_PREFIX_PATH scan ──────────────────────────────────────────

class TestNodeInfoFallback:
    def test_fallback_to_ament_scan(self, make_ament_tree):
        prefix, _ = make_ament_tree('my_pkg', {
            'groups': {'nav': {'color': 'bold blue', 'nodes': ['talker']}}
        })
        stdout, _, _ = run_node_info(prefix, SAMPLE_INFO)
        assert_segment_colored(stdout, '/talker', '34;1')

    def test_passthrough_when_no_config(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '/talker' in stdout
        first_line = stdout.splitlines()[0]
        assert '\033[' not in first_line
