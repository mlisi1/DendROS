"""Tests for dendros_service_list.py colorization."""

import os
import sys
import subprocess

import pytest
import yaml

REPO_ROOT         = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SERVICE_LIST_PATH = os.path.join(REPO_ROOT, 'dendROS', 'dendros_service_list.py')

from conftest import assert_segment_colored, assert_segment_uncolored, colored_segments, strip_ansi


# ── Helper ────────────────────────────────────────────────────────────────────

def run_service_list(tmp_prefix, services, global_cfg=None, node_colors=None, timeout=10):
    """Run dendros_service_list.py with service paths as stdin; return (stdout, stderr, rc)."""
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

    stdin = '\n'.join(services) + '\n'
    result = subprocess.run(
        [sys.executable, SERVICE_LIST_PATH],
        input=stdin.encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# ── Default service dimming ───────────────────────────────────────────────────

class TestDefaultDimming:
    """Standard ROS 2 parameter/logger services must be rendered dim."""

    DEFAULT_SERVICES = [
        '/talker/describe_parameters',
        '/talker/get_parameter_types',
        '/talker/get_parameters',
        '/talker/list_parameters',
        '/talker/set_parameters',
        '/talker/set_parameters_atomically',
        '/talker/get_loggers',
        '/talker/set_logger_levels',
        '/talker/get_type_description',
    ]

    def test_all_default_services_contain_dim(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        for svc in self.DEFAULT_SERVICES:
            stdout, _, _ = run_service_list(str(tmp_path), [svc], node_colors=nc)
            assert '\033[2m' in stdout, \
                f'Expected {svc!r} to be dimmed, got: {stdout!r}'

    def test_default_service_uses_node_color_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/set_parameters'],
                                        node_colors=nc)
        # Name rendered as node color + dim
        assert '\033[34m\033[2m/talker/set_parameters\033[0m' in stdout

    def test_default_service_plain_dim_without_node_color(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/unknown/set_parameters'],
                                        node_colors=nc)
        assert '\033[2m/unknown/set_parameters\033[0m' in stdout

    def test_default_service_no_tag(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/set_parameters'],
                                        node_colors=nc)
        assert '[TLK]' not in stdout

    def test_non_default_service_not_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_custom_service'],
                                        node_colors=nc)
        assert_segment_colored(stdout, '/talker/my_custom_service', '34')

    def test_default_service_with_type_flag(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        line = '/talker/set_parameters [rcl_interfaces/srv/SetParameters]'
        stdout, _, _ = run_service_list(str(tmp_path), [line], node_colors=nc)
        # Name: node color + dim; type: plain dim inside brackets
        assert '\033[34m\033[2m/talker/set_parameters\033[0m' in stdout
        assert '[\033[2mrcl_interfaces/srv/SetParameters\033[0m]' in stdout

    def test_default_service_with_type_no_node_color(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        line = '/unknown/set_parameters [rcl_interfaces/srv/SetParameters]'
        stdout, _, _ = run_service_list(str(tmp_path), [line], node_colors=nc)
        assert '\033[2m/unknown/set_parameters\033[0m' in stdout
        assert '[\033[2mrcl_interfaces/srv/SetParameters\033[0m]' in stdout


# ── Node color resolution via prefix ─────────────────────────────────────────

class TestServiceNodeColor:
    """Services are colored based on their owning-node path prefix."""

    def test_simple_prefix_matched(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'], node_colors=nc)
        assert_segment_colored(stdout, '/talker/my_service', '32')

    def test_namespaced_prefix_matched(self, tmp_path):
        nc = {'color_map': {'talker': '33'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/ns/talker/my_service'],
                                        node_colors=nc)
        assert_segment_colored(stdout, '/ns/talker/my_service', '33')

    def test_multiple_services_from_same_node(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path),
                                        ['/talker/svc_a', '/talker/svc_b'], node_colors=nc)
        assert_segment_colored(stdout, '/talker/svc_a', '34')
        assert_segment_colored(stdout, '/talker/svc_b', '34')

    def test_standalone_service_uncolored(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/standalone_service'], node_colors=nc)
        assert_segment_uncolored(stdout, '/standalone_service')

    def test_unmatched_prefix_passthrough(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/other_node/my_service'],
                                        node_colors=nc)
        assert_segment_uncolored(stdout, '/other_node/my_service')

    def test_wildcard_pattern(self, tmp_path):
        nc = {'color_map': {'nav2_*': '36'}, 'tag_map': {'nav2_*': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path),
                                        ['/nav2_controller/my_service',
                                         '/nav2_planner/my_service'], node_colors=nc)
        assert_segment_colored(stdout, '/nav2_controller/my_service', '36')
        assert_segment_colored(stdout, '/nav2_planner/my_service', '36')

    def test_no_shared_file_passthrough(self, tmp_path):
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/some_service'])
        assert '/talker/some_service' in stdout
        assert '\033[' not in stdout

    def test_empty_lines_preserved(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/svc', '', '/other/svc'],
                                        node_colors=nc)
        assert '' in stdout.splitlines()


# ── -t flag: type annotation dimmed ──────────────────────────────────────────

class TestServiceListTypeFlag:
    """-t flag appends ' [type]'; type content must be rendered dim."""

    def test_type_dimmed_for_matched_service(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        line = '/talker/my_service [custom_msgs/srv/MySvc]'
        stdout, _, _ = run_service_list(str(tmp_path), [line], node_colors=nc)
        assert_segment_colored(stdout, '/talker/my_service', '32')
        assert '[\033[2mcustom_msgs/srv/MySvc\033[0m]' in stdout

    def test_type_dimmed_for_unmatched_service(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        line = '/unknown/my_service [custom_msgs/srv/MySvc]'
        stdout, _, _ = run_service_list(str(tmp_path), [line], node_colors=nc)
        assert '[\033[2mcustom_msgs/srv/MySvc\033[0m]' in stdout

    def test_type_not_colored_with_node_color(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        line = '/talker/my_service [custom_msgs/srv/MySvc]'
        stdout, _, _ = run_service_list(str(tmp_path), [line], node_colors=nc)
        # Type content must not be wrapped in the node's color code
        assert '\033[32mcustom_msgs' not in stdout

    def test_no_type_unchanged(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'], node_colors=nc)
        assert '[' not in strip_ansi(stdout)  # no spurious type bracket in plain text

    def test_tag_plus_type(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        line = '/talker/my_service [custom_msgs/srv/MySvc]'
        stdout, _, _ = run_service_list(str(tmp_path), [line], node_colors=nc)
        assert '[TLK]' in stdout
        assert '[\033[2mcustom_msgs/srv/MySvc\033[0m]' in stdout


# ── Tag badge (always left / before) ─────────────────────────────────────────

class TestServiceListTag:
    """Tag badge appears to the left of the service path."""

    def test_tag_shown_before_service(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'], node_colors=nc)
        assert '[TLK]' in stdout
        # Badge must appear before the service name on the same line
        line = [l for l in stdout.splitlines() if '/talker/my_service' in l][0]
        assert line.index('[TLK]') < line.index('/talker/my_service')

    def test_tag_hidden_when_show_tag_cli_false(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'],
                                        node_colors=nc,
                                        global_cfg={'show_tag_cli': False})
        assert '[TLK]' not in stdout

    def test_tag_hidden_when_label_empty(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'], node_colors=nc)
        assert '[' not in stdout or '[[' not in stdout
        # Specifically no badge brackets around an empty string
        assert '[] ' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': 'TLK'},
              'style_map': {'talker': 'inverted'}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'], node_colors=nc)
        # Inverted tag uses ;7 reverse-video
        assert '\033[34;7m[TLK]' in stdout

    def test_unmatched_tag(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_service_list(
            str(tmp_path), ['/unknown/my_service'], node_colors=nc,
            global_cfg={'unmatched_color': 'white', 'unmatched_tag': '?'})
        assert '[?]' in stdout


# ── Unmatched / dim_unmatched ─────────────────────────────────────────────────

class TestServiceListUnmatched:

    def test_unmatched_color(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_service_list(
            str(tmp_path), ['/unknown/my_service'], node_colors=nc,
            global_cfg={'unmatched_color': 'cyan'})
        assert '\033[' in stdout  # some color applied

    def test_dim_unmatched(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_service_list(
            str(tmp_path), ['/unknown/my_service'], node_colors=nc,
            global_cfg={'dim_unmatched': True})
        assert f'\033[2m/unknown/my_service\033[0m' in stdout

    def test_passthrough_when_no_config(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/unknown/my_service'], node_colors=nc)
        assert_segment_uncolored(stdout, '/unknown/my_service')


# ── AMENT_PREFIX_PATH fallback ────────────────────────────────────────────────

class TestServiceListFallback:

    def test_fallback_scan_colors_service(self, tmp_path):
        cfg_dir = tmp_path / 'share' / 'my_pkg' / 'config'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'dendROS.yaml').write_text(yaml.dump({
            'groups': {'nav': {'color': 'bold green', 'label': 'NAV', 'nodes': ['talker']}}
        }))
        # No node_colors.yaml — must fall back to AMENT scan
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'])
        assert '\033[' in stdout


# ── show_default_services config option ──────────────────────────────────────

class TestShowDefaultServices:
    """show_default_services: false hides standard parameter/logger services entirely."""

    DEFAULT_SVCS = [
        '/talker/describe_parameters',
        '/talker/get_parameter_types',
        '/talker/get_parameters',
        '/talker/list_parameters',
        '/talker/set_parameters',
        '/talker/set_parameters_atomically',
        '/talker/get_loggers',
        '/talker/set_logger_levels',
        '/talker/get_type_description',
    ]

    def test_default_services_hidden_when_disabled(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        for svc in self.DEFAULT_SVCS:
            stdout, _, _ = run_service_list(str(tmp_path), [svc], node_colors=nc,
                                            global_cfg={'show_default_services': False})
            assert svc not in stdout, f'Expected {svc!r} to be hidden'

    def test_non_default_service_still_shown(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/my_service'],
                                        node_colors=nc,
                                        global_cfg={'show_default_services': False})
        assert '/talker/my_service' in stdout

    def test_mixed_list_only_shows_custom(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        lines = ['/talker/set_parameters', '/talker/my_service', '/talker/get_parameters']
        stdout, _, _ = run_service_list(str(tmp_path), lines, node_colors=nc,
                                        global_cfg={'show_default_services': False})
        assert '/talker/my_service' in stdout
        assert '/talker/set_parameters' not in stdout
        assert '/talker/get_parameters' not in stdout

    def test_default_services_shown_by_default(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_service_list(str(tmp_path), ['/talker/set_parameters'],
                                        node_colors=nc)
        assert '/talker/set_parameters' in stdout

    def test_hidden_with_type_flag(self, tmp_path):
        nc = {'color_map': {'talker': '34'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        line = '/talker/set_parameters [rcl_interfaces/srv/SetParameters]'
        stdout, _, _ = run_service_list(str(tmp_path), [line], node_colors=nc,
                                        global_cfg={'show_default_services': False})
        assert 'set_parameters' not in stdout
