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

# Rich sample that exercises every section, including non-None Service/Action Clients
SAMPLE_INFO = """\
/motion_controller
  Subscribers:
    /fused_odom: std_msgs/msg/String
    /global_plan: std_msgs/msg/String
  Publishers:
    /cmd_vel: std_msgs/msg/String
    /rosout: rcl_interfaces/msg/Log
  Service Servers:
    /motion_controller/stop: std_srvs/srv/Trigger
  Service Clients:
    /path_planner/compute_path: std_srvs/srv/Trigger
  Action Servers:
    /dock: example_interfaces/action/Fibonacci
  Action Clients:
    /navigate_to_pose: nav2_msgs/action/NavigateToPose
"""

# Node color used in most tests
_MC = 'motion_controller'
_MC_CODE = '33'   # bold yellow


def _nc(extra=None):
    """Return a node_colors dict for motion_controller + optional extra entries."""
    d = {
        'color_map': {_MC: _MC_CODE},
        'tag_map':   {_MC: 'CTL'},
        'style_map': {},
    }
    if extra:
        for k, v in extra.items():
            d['color_map'][k] = v[0]
            d['tag_map'][k]   = v[1]
    return d


def run_node_info(tmp_prefix, stdin_text, global_cfg=None, node_colors=None,
                  topic_publishers=None, service_servers=None, action_servers=None,
                  topic_subscribers=None, timeout=10):
    """Run dendros_node_info.py with stdin_text; return (stdout, stderr, rc).

    Inject provider maps to avoid live graph queries in tests:
      topic_publishers  — {topic:   [node_basename, ...]}  (Subscribers)
      service_servers   — {service: [node_basename, ...]}  (Service Clients)
      action_servers    — {action:  [node_basename, ...]}  (Action Clients)
      topic_subscribers — {topic:   [node_basename, ...]}  (Publishers squares)
    Pass None for any type (defaults to empty dict — graph skipped).
    """
    env = os.environ.copy()
    env['AMENT_PREFIX_PATH'] = tmp_prefix
    env.pop('ROS_DISTRO', None)
    env['HOME'] = tmp_prefix

    # Always inject overrides so tests never hit the live ROS 2 graph.
    env['DENDROS_TOPIC_PUBLISHERS']  = json.dumps(topic_publishers  or {})
    env['DENDROS_SERVICE_SERVERS']   = json.dumps(service_servers   or {})
    env['DENDROS_ACTION_SERVERS']    = json.dumps(action_servers    or {})
    env['DENDROS_TOPIC_SUBSCRIBERS'] = json.dumps(topic_subscribers or {})

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
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert_segment_colored(stdout, '/motion_controller', _MC_CODE)

    def test_tag_after_position(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'tag_position': 'after'},
                                     node_colors=_nc())
        assert stdout.index('/motion_controller') < stdout.index('[CTL]')

    def test_tag_before_position(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'tag_position': 'before'},
                                     node_colors=_nc())
        assert stdout.index('[CTL]') < stdout.index('/motion_controller')

    def test_no_tag_when_show_group_tag_false(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'show_group_tag': False},
                                     node_colors=_nc())
        assert '[CTL]' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO,
                                     global_cfg={'tag_style': 'inverted'},
                                     node_colors=_nc())
        assert f';7m[CTL]' in stdout

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
        nc = {'color_map': {_MC: _MC_CODE}, 'tag_map': {_MC: ''}, 'style_map': {}}
        info = f'/my_ns/{_MC}\n  Publishers:\n    /cmd_vel: std_msgs/msg/String\n'
        stdout, _, _ = run_node_info(str(tmp_path), info, node_colors=nc)
        assert_segment_colored(stdout, f'/my_ns/{_MC}', _MC_CODE)

    def test_no_config_passthrough(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '/motion_controller' in stdout
        first_line = stdout.splitlines()[0]
        assert '\033[' not in first_line


# ── Section headers ────────────────────────────────────────────────────────────

class TestNodeInfoSectionHeaders:
    def test_subscribers_bold(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[1m  Subscribers:\033[0m' in stdout

    def test_publishers_bold(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[1m  Publishers:\033[0m' in stdout

    def test_service_servers_bold(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[1m  Service Servers:\033[0m' in stdout

    def test_service_clients_bold(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[1m  Service Clients:\033[0m' in stdout

    def test_action_servers_bold(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[1m  Action Servers:\033[0m' in stdout

    def test_action_clients_bold(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[1m  Action Clients:\033[0m' in stdout

    def test_headers_bold_without_config(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '\033[1m  Publishers:\033[0m' in stdout


# ── Output sections (node's own color, no tag) ────────────────────────────────

class TestNodeInfoOutputSections:
    def test_publisher_entry_colored(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert_segment_colored(stdout, '/cmd_vel', _MC_CODE)

    def test_publisher_second_entry_colored(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert_segment_colored(stdout, '/rosout', _MC_CODE)

    def test_service_server_entry_colored(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert_segment_colored(stdout, '/motion_controller/stop', _MC_CODE)

    def test_action_server_entry_colored(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert_segment_colored(stdout, '/dock', _MC_CODE)

    def test_output_entries_have_no_tag(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        tag_lines = [l for l in stdout.splitlines() if '[CTL]' in l]
        # Badge appears only on the node name line
        assert len(tag_lines) == 1
        assert '/motion_controller' in tag_lines[0]
        assert '/cmd_vel' not in tag_lines[0]

    def test_none_entry_not_node_colored(self, tmp_path):
        info = '/motion_controller\n  Service Clients:\n    (None)\n'
        stdout, _, _ = run_node_info(str(tmp_path), info, node_colors=_nc())
        for line in stdout.splitlines():
            if '(None)' in line:
                assert f'\033[{_MC_CODE}m(None)' not in line

    def test_output_unaffected_when_node_unmatched(self, tmp_path):
        nc = {'color_map': {'other': '34;1'}, 'tag_map': {'other': ''}, 'style_map': {}}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc)
        assert_segment_uncolored(stdout, '/cmd_vel')
        assert_segment_uncolored(stdout, '/motion_controller/stop')


# ── Input sections (provider's color) ─────────────────────────────────────────

class TestNodeInfoInputSections:

    # ── Subscribers ───────────────────────────────────────────────────────────

    def test_subscriber_colored_by_publisher(self, tmp_path):
        nc = _nc({'sensor_fusion': ('32', 'FUS')})
        tp = {'/fused_odom': ['sensor_fusion']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/fused_odom', '32')

    def test_subscriber_uses_publisher_color_not_own(self, tmp_path):
        nc = _nc({'path_planner': ('34;1', 'PLN')})
        tp = {'/global_plan': ['path_planner']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/global_plan', '34;1')  # path_planner's color

    def test_subscriber_no_tag(self, tmp_path):
        nc = _nc({'sensor_fusion': ('32', 'FUS')})
        tp = {'/fused_odom': ['sensor_fusion']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        sub_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        assert '[FUS]' not in sub_line

    def test_subscriber_uncolored_when_publisher_unknown(self, tmp_path):
        tp = {'/fused_odom': ['unknown_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     topic_publishers=tp)
        assert_segment_uncolored(stdout, '/fused_odom')

    def test_subscriber_uncolored_when_no_publisher(self, tmp_path):
        tp = {'/fused_odom': []}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     topic_publishers=tp)
        assert_segment_uncolored(stdout, '/fused_odom')

    def test_multiple_subscribers_independently_colored(self, tmp_path):
        nc = _nc({'sensor_fusion': ('32', 'FUS'), 'path_planner': ('34;1', 'PLN')})
        tp = {'/fused_odom': ['sensor_fusion'], '/global_plan': ['path_planner']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/fused_odom',  '32')
        assert_segment_colored(stdout, '/global_plan', '34;1')

    # ── Service Clients ───────────────────────────────────────────────────────

    def test_service_client_colored_by_server(self, tmp_path):
        nc = _nc({'path_planner': ('34;1', 'PLN')})
        ss = {'/path_planner/compute_path': ['path_planner']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     service_servers=ss)
        assert_segment_colored(stdout, '/path_planner/compute_path', '34;1')

    def test_service_client_no_tag(self, tmp_path):
        nc = _nc({'path_planner': ('34;1', 'PLN')})
        ss = {'/path_planner/compute_path': ['path_planner']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     service_servers=ss)
        svc_line = next(l for l in stdout.splitlines()
                        if '/path_planner/compute_path' in l)
        assert '[PLN]' not in svc_line

    def test_service_client_uncolored_when_server_unknown(self, tmp_path):
        ss = {'/path_planner/compute_path': ['unknown_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     service_servers=ss)
        assert_segment_uncolored(stdout, '/path_planner/compute_path')

    def test_service_client_uncolored_with_empty_map(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert_segment_uncolored(stdout, '/path_planner/compute_path')

    # ── Action Clients ────────────────────────────────────────────────────────

    def test_action_client_colored_by_server(self, tmp_path):
        nc = _nc({'nav2_bt_navigator': ('35', 'NAV')})
        as_ = {'/navigate_to_pose': ['nav2_bt_navigator']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     action_servers=as_)
        assert_segment_colored(stdout, '/navigate_to_pose', '35')

    def test_action_client_no_tag(self, tmp_path):
        nc = _nc({'nav2_bt_navigator': ('35', 'NAV')})
        as_ = {'/navigate_to_pose': ['nav2_bt_navigator']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     action_servers=as_)
        act_line = next(l for l in stdout.splitlines() if '/navigate_to_pose' in l)
        assert '[NAV]' not in act_line

    def test_action_client_uncolored_when_server_unknown(self, tmp_path):
        as_ = {'/navigate_to_pose': ['unknown_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     action_servers=as_)
        assert_segment_uncolored(stdout, '/navigate_to_pose')

    def test_action_client_uncolored_with_empty_map(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert_segment_uncolored(stdout, '/navigate_to_pose')

    def test_all_input_kinds_colored_independently(self, tmp_path):
        """Sub, Service Client, and Action Client each use their provider's color."""
        nc = _nc({
            'sensor_fusion':   ('32',   'FUS'),
            'path_planner':    ('34;1', 'PLN'),
            'bt_navigator':    ('35',   'BT'),
        })
        tp  = {'/fused_odom': ['sensor_fusion']}
        ss  = {'/path_planner/compute_path': ['path_planner']}
        as_ = {'/navigate_to_pose': ['bt_navigator']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp,
                                     service_servers=ss,
                                     action_servers=as_)
        assert_segment_colored(stdout, '/fused_odom',               '32')
        assert_segment_colored(stdout, '/path_planner/compute_path', '34;1')
        assert_segment_colored(stdout, '/navigate_to_pose',          '35')


# ── Multiple providers → inverted-bg number indicators ────────────────────────

class TestNodeInfoMultipleProviders:
    def test_two_publishers_show_two_indicators(self, tmp_path):
        """Two publishers from different groups → two inverted-bg count indicators."""
        nc = _nc({'pub_a': ('32', 'A'), 'pub_b': ('35', 'B')})
        tp = {'/fused_odom': ['pub_a', 'pub_b']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/fused_odom', '32')
        fused_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        assert '\033[32;7m1\033[0m' in fused_line  # pub_a count
        assert '\033[35;7m1\033[0m' in fused_line  # pub_b count

    def test_indicators_appear_after_type(self, tmp_path):
        """Indicators are AFTER the type annotation, not before the topic name."""
        nc = _nc({'pub_a': ('32', 'A'), 'pub_b': ('35', 'B')})
        tp = {'/fused_odom': ['pub_a', 'pub_b']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        fused_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        # Topic name before the first indicator
        assert fused_line.index('/fused_odom') < fused_line.index('\033[32;7m')

    def test_topic_names_at_same_indent_as_service_entries(self, tmp_path):
        """Topic names stay at column 4 — same as Service Server entries."""
        import re as _re
        _ansi = _re.compile(r'\033\[[0-9;]*m')
        nc = _nc({'pub_a': ('32', 'A'), 'pub_b': ('35', 'B')})
        tp = {'/fused_odom': ['pub_a', 'pub_b'], '/global_plan': ['pub_a']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        sub_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        svc_line = next(l for l in stdout.splitlines() if '/motion_controller/stop' in l)
        sub_col = _ansi.sub('', sub_line).index('/fused_odom')
        svc_col = _ansi.sub('', svc_line).index('/motion_controller/stop')
        assert sub_col == svc_col

    def test_primary_name_color_unaffected_by_extra_providers(self, tmp_path):
        nc = _nc({'pub_a': ('32', 'A'), 'pub_b': ('35', 'B'), 'pub_c': ('36', 'C')})
        tp = {'/fused_odom': ['pub_a', 'pub_b', 'pub_c']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/fused_odom', '32')

    def test_four_publishers_four_indicators(self, tmp_path):
        nc = _nc({'p1': ('31', ''), 'p2': ('32', ''), 'p3': ('36', '')})
        tp = {'/fused_odom': ['motion_controller', 'p1', 'p2', 'p3']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        fused_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        assert '\033[33;7m1\033[0m' in fused_line  # motion_controller
        assert '\033[31;7m1\033[0m' in fused_line  # p1
        assert '\033[32;7m1\033[0m' in fused_line  # p2
        assert '\033[36;7m1\033[0m' in fused_line  # p3

    def test_same_color_nodes_counted_together(self, tmp_path):
        """Two nodes from the same group aggregate into a single count of 2."""
        nc = _nc({'pub_a': ('32', 'A'), 'pub_b': ('32', 'B')})
        tp = {'/fused_odom': ['pub_a', 'pub_b']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        fused_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        assert '\033[32;7m2\033[0m' in fused_line
        assert fused_line.count('\033[32;7m') == 1

    def test_single_provider_shows_count_one(self, tmp_path):
        nc = _nc({'sensor_fusion': ('32', 'FUS')})
        tp = {'/fused_odom': ['sensor_fusion']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        fused_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        assert '\033[32;7m1\033[0m' in fused_line

    def test_no_providers_no_indicator(self, tmp_path):
        tp = {'/fused_odom': [], '/global_plan': []}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     topic_publishers=tp)
        fused_line = next(l for l in stdout.splitlines() if '/fused_odom' in l)
        assert ';7m' not in fused_line

    def test_multiple_service_client_servers_show_squares(self, tmp_path):
        """Service clients keep trailing ■ squares (not inverted-bg numbers)."""
        nc = _nc({'server_a': ('32', 'A'), 'server_b': ('35', 'B')})
        ss = {'/path_planner/compute_path': ['server_a', 'server_b']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     service_servers=ss)
        assert_segment_colored(stdout, '/path_planner/compute_path', '32')
        svc_line = next(l for l in stdout.splitlines()
                        if '/path_planner/compute_path' in l)
        assert '\033[35m■\033[0m' in svc_line


# ── Type annotation dimming ────────────────────────────────────────────────────

class TestNodeInfoTypeDimming:
    def test_service_server_type_dimmed(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[2mstd_srvs/srv/Trigger\033[0m' in stdout

    def test_publisher_type_dimmed(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[2mstd_msgs/msg/String\033[0m' in stdout

    def test_action_server_type_dimmed(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc())
        assert '\033[2mexample_interfaces/action/Fibonacci\033[0m' in stdout

    def test_types_dimmed_without_config(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '\033[2mstd_msgs/msg/String\033[0m' in stdout

    def test_none_entry_dimmed(self, tmp_path):
        info = '/motion_controller\n  Service Clients:\n    (None)\n'
        stdout, _, _ = run_node_info(str(tmp_path), info, node_colors=_nc())
        assert '\033[2m(None)\033[0m' in stdout

    def test_subscriber_type_dimmed_when_colored(self, tmp_path):
        nc = _nc({'sensor_fusion': ('32', 'FUS')})
        tp = {'/fused_odom': ['sensor_fusion']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert '\033[2mstd_msgs/msg/String\033[0m' in stdout


# ── Fallback: AMENT_PREFIX_PATH scan ──────────────────────────────────────────

class TestNodeInfoFallback:
    def test_fallback_to_ament_scan(self, make_ament_tree):
        # 'bold yellow' resolves to '33;1', not bare '33'
        prefix, _ = make_ament_tree('my_pkg', {
            'groups': {'ctl': {'color': 'bold yellow', 'nodes': [_MC]}}
        })
        stdout, _, _ = run_node_info(prefix, SAMPLE_INFO)
        assert_segment_colored(stdout, '/motion_controller', '33;1')

    def test_passthrough_when_no_config(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO)
        assert '/motion_controller' in stdout
        first_line = stdout.splitlines()[0]
        assert '\033[' not in first_line


# ── Publisher section indicators (subscriber counts) ──────────────────────────

class TestNodeInfoPublisherSquares:
    """Inverted-bg count indicators trail AFTER the type in the Publishers section."""

    def test_subscriber_indicator_shown_after_type(self, tmp_path):
        nc = _nc({'diagnostics_monitor': ('35', 'MON')})
        ts = {'/cmd_vel': ['diagnostics_monitor']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_subscribers=ts)
        cmd_line = next(l for l in stdout.splitlines() if '/cmd_vel' in l)
        assert '\033[35;7m1\033[0m' in cmd_line
        # Indicator is AFTER the topic name (right side)
        assert cmd_line.index('/cmd_vel') < cmd_line.index('\033[35;7m')

    def test_publisher_name_still_colored_with_own_color(self, tmp_path):
        nc = _nc({'diagnostics_monitor': ('35', 'MON')})
        ts = {'/cmd_vel': ['diagnostics_monitor']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_subscribers=ts)
        assert_segment_colored(stdout, '/cmd_vel', _MC_CODE)

    def test_published_topic_name_at_same_indent_as_service_entries(self, tmp_path):
        """Publisher entries have the same 4-space indent as Service Server entries."""
        import re as _re
        _ansi = _re.compile(r'\033\[[0-9;]*m')
        nc = _nc({'sub_a': ('31', 'A'), 'sub_b': ('35', 'B')})
        ts = {'/cmd_vel': ['sub_a', 'sub_b']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_subscribers=ts)
        pub_line = next(l for l in stdout.splitlines() if '/cmd_vel' in l)
        svc_line = next(l for l in stdout.splitlines() if '/motion_controller/stop' in l)
        pub_col = _ansi.sub('', pub_line).index('/cmd_vel')
        svc_col = _ansi.sub('', svc_line).index('/motion_controller/stop')
        assert pub_col == svc_col

    def test_multiple_subscribers_multiple_indicators(self, tmp_path):
        nc = _nc({'sub_a': ('31', 'A'), 'sub_b': ('35', 'B')})
        ts = {'/cmd_vel': ['sub_a', 'sub_b']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_subscribers=ts)
        cmd_line = next(l for l in stdout.splitlines() if '/cmd_vel' in l)
        assert '\033[31;7m1\033[0m' in cmd_line
        assert '\033[35;7m1\033[0m' in cmd_line

    def test_no_indicator_when_none_known(self, tmp_path):
        ts = {'/cmd_vel': [], '/rosout': []}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     topic_subscribers=ts)
        cmd_line = next(l for l in stdout.splitlines() if '/cmd_vel' in l)
        assert ';7m' not in cmd_line

    def test_same_color_subscribers_counted_together(self, tmp_path):
        nc = _nc({'sub_a': ('35', 'A'), 'sub_b': ('35', 'B')})
        ts = {'/cmd_vel': ['sub_a', 'sub_b']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=nc,
                                     topic_subscribers=ts)
        cmd_line = next(l for l in stdout.splitlines() if '/cmd_vel' in l)
        assert '\033[35;7m2\033[0m' in cmd_line
        assert cmd_line.count('\033[35;7m') == 1

    def test_unknown_subscriber_produces_no_indicator(self, tmp_path):
        ts = {'/cmd_vel': ['unknown_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     topic_subscribers=ts)
        cmd_line = next(l for l in stdout.splitlines() if '/cmd_vel' in l)
        assert ';7m' not in cmd_line

    def test_no_indicators_on_service_servers(self, tmp_path):
        """Service Server entries must not get any indicators."""
        ts = {'/motion_controller/stop': ['some_node']}
        stdout, _, _ = run_node_info(str(tmp_path), SAMPLE_INFO, node_colors=_nc(),
                                     topic_subscribers=ts)
        svc_line = next(l for l in stdout.splitlines()
                        if '/motion_controller/stop' in l)
        assert ';7m' not in svc_line


# ── Bracket-format entries (name [type]) ─────────────────────────────────────

class TestNodeInfoBracketFormat:
    """ROS 2 versions that output 'name [type]' instead of 'name: type'."""

    BRACKET_INFO = """\
/motion_controller
  Action Clients:
    /navigate_to_pose [nav2_msgs/action/NavigateToPose]
  Subscribers:
    /fused_odom [std_msgs/msg/String]
"""

    def test_action_client_bracket_format_colored(self, tmp_path):
        nc = _nc({'nav2_bt_navigator': ('35', 'NAV')})
        as_ = {'/navigate_to_pose': ['nav2_bt_navigator']}
        stdout, _, _ = run_node_info(str(tmp_path), self.BRACKET_INFO, node_colors=nc,
                                     action_servers=as_)
        assert_segment_colored(stdout, '/navigate_to_pose', '35')

    def test_action_client_bracket_format_type_dimmed(self, tmp_path):
        stdout, _, _ = run_node_info(str(tmp_path), self.BRACKET_INFO, node_colors=_nc())
        assert '\033[2mnav2_msgs/action/NavigateToPose\033[0m' in stdout

    def test_subscriber_bracket_format_colored(self, tmp_path):
        nc = _nc({'sensor_fusion': ('32', 'FUS')})
        tp = {'/fused_odom': ['sensor_fusion']}
        stdout, _, _ = run_node_info(str(tmp_path), self.BRACKET_INFO, node_colors=nc,
                                     topic_publishers=tp)
        assert_segment_colored(stdout, '/fused_odom', '32')
