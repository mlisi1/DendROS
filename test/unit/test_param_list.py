"""Tests for dendros_param_list.py colorization."""

import os
import sys
import subprocess

import pytest
import yaml

REPO_ROOT       = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PARAM_LIST_PATH = os.path.join(REPO_ROOT, 'dendROS', 'dendros_param_list.py')

from conftest import assert_segment_colored, assert_segment_uncolored, colored_segments, strip_ansi


# ── Helper ────────────────────────────────────────────────────────────────────

def run_param_list(tmp_prefix, lines, global_cfg=None, node_colors=None,
                   argv_extra=None, timeout=10):
    """Run dendros_param_list.py with text lines as stdin; return (stdout, stderr, rc).

    argv_extra: list of extra args appended to the command (mirrors ${@:3} from the shell).
    """
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

    stdin = '\n'.join(lines) + '\n'
    cmd = [sys.executable, PARAM_LIST_PATH] + (argv_extra or [])
    result = subprocess.run(
        cmd,
        input=stdin.encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# ── Node header colorization ──────────────────────────────────────────────────

class TestParamNodeHeader:
    """Node header lines (/node_name:) are colored with the group's color."""

    def test_matched_node_header_colored(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:'], node_colors=nc)
        assert '\033[32m/talker:\033[0m' in stdout

    def test_unmatched_node_header_passthrough(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/unknown_node:'], node_colors=nc)
        assert_segment_uncolored(stdout, '/unknown_node:')

    def test_multiple_node_headers(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'listener': '34'},
              'tag_map': {'talker': '', 'listener': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/talker:', '  p1', '/listener:', '  p2'], node_colors=nc)
        assert '\033[32m/talker:\033[0m' in stdout
        assert '\033[34m/listener:\033[0m' in stdout

    def test_namespaced_node_header(self, tmp_path):
        nc = {'color_map': {'talker': '33'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/my_ns/talker:'], node_colors=nc)
        assert '\033[33m/my_ns/talker:\033[0m' in stdout

    def test_wildcard_pattern(self, tmp_path):
        nc = {'color_map': {'nav2_*': '35'}, 'tag_map': {'nav2_*': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/nav2_planner:'], node_colors=nc)
        assert '\033[35m/nav2_planner:\033[0m' in stdout

    def test_no_config_passthrough(self, tmp_path):
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:'])
        assert '\033[' not in stdout
        assert '/talker:' in stdout

    def test_empty_lines_preserved(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/talker:', '', '  p1'], node_colors=nc)
        assert '' in stdout.splitlines()


# ── Param line colorization (dimmed) ─────────────────────────────────────────

class TestParamLines:
    """Param lines (indented) use the current node's color, dimmed."""

    def test_param_colored_dim_with_node_color(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:', '  use_sim_time'],
                                      node_colors=nc)
        assert '\033[32m\033[2muse_sim_time\033[0m' in stdout

    def test_param_indent_preserved(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:', '  use_sim_time'],
                                      node_colors=nc)
        line = [l for l in stdout.splitlines() if 'use_sim_time' in l][0]
        plain = strip_ansi(line)
        assert plain.startswith('  ')

    def test_param_under_unmatched_node_passthrough(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/unknown:', '  some_param'], node_colors=nc)
        assert_segment_uncolored(stdout, 'some_param')

    def test_params_inherit_node_color_change(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'listener': '34'},
              'tag_map': {'talker': '', 'listener': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path),
            ['/talker:', '  p1', '/listener:', '  p2'],
            node_colors=nc)
        assert '\033[32m\033[2mp1\033[0m' in stdout
        assert '\033[34m\033[2mp2\033[0m' in stdout

    def test_multiple_params_same_node(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/talker:', '  param_a', '  param_b'], node_colors=nc)
        assert '\033[32m\033[2mparam_a\033[0m' in stdout
        assert '\033[32m\033[2mparam_b\033[0m' in stdout

    def test_param_no_config_passthrough(self, tmp_path):
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:', '  use_sim_time'])
        assert '\033[' not in stdout


# ── --param-type flag: type annotation dimmed ─────────────────────────────────

class TestParamListTypeFlag:
    """--param-type appends ' (type)'; type content must be rendered dim."""

    def test_type_dimmed_for_matched_param(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/talker:', '  use_sim_time (bool)'], node_colors=nc)
        assert '(\033[2mbool\033[0m)' in stdout

    def test_type_dimmed_for_unmatched_param(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/unknown:', '  foo (integer)'], node_colors=nc)
        assert '(\033[2minteger\033[0m)' in stdout

    def test_param_name_and_type_both_present(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/talker:', '  my_param (string)'], node_colors=nc)
        assert '\033[32m\033[2mmy_param\033[0m' in stdout
        assert '(\033[2mstring\033[0m)' in stdout

    def test_no_type_no_parens(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:', '  my_param'],
                                      node_colors=nc)
        assert '(' not in strip_ansi(stdout)


# ── Tag badge ─────────────────────────────────────────────────────────────────

class TestParamListTag:
    """Tag badge appears left of the node header when show_tag_cli is true."""

    def test_tag_shown_before_node_header(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:'], node_colors=nc)
        assert '[TLK]' in stdout
        line = [l for l in stdout.splitlines() if '/talker:' in strip_ansi(l)][0]
        assert line.index('[TLK]') < line.index('/talker:')

    def test_tag_hidden_when_show_tag_cli_false(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:'],
                                      node_colors=nc,
                                      global_cfg={'show_tag_cli': False})
        assert '[TLK]' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'},
              'style_map': {'talker': 'inverted'}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:'], node_colors=nc)
        assert '\033[32;7m[TLK]' in stdout

    def test_unmatched_tag(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/unknown:'], node_colors=nc,
            global_cfg={'unmatched_color': 'white', 'unmatched_tag': '?'})
        assert '[?]' in stdout

    def test_tag_not_shown_on_param_lines(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:', '  p1'], node_colors=nc)
        param_line = [l for l in stdout.splitlines() if 'p1' in strip_ansi(l)][0]
        assert '[TLK]' not in param_line


# ── Unmatched / dim_unmatched ─────────────────────────────────────────────────

class TestParamListUnmatched:

    def test_unmatched_color_applied_to_header(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/unknown:'], node_colors=nc,
            global_cfg={'unmatched_color': 'cyan'})
        assert '\033[' in stdout

    def test_dim_unmatched_header(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/unknown:'], node_colors=nc,
            global_cfg={'dim_unmatched': True})
        assert '\033[2m/unknown:\033[0m' in stdout

    def test_dim_unmatched_param(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(
            str(tmp_path), ['/unknown:', '  my_param'], node_colors=nc,
            global_cfg={'dim_unmatched': True})
        assert '\033[2mmy_param\033[0m' in stdout

    def test_passthrough_when_no_config(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['/unknown:', '  p1'], node_colors=nc)
        assert_segment_uncolored(stdout, '/unknown:')
        assert_segment_uncolored(stdout, 'p1')


# ── AMENT_PREFIX_PATH fallback ────────────────────────────────────────────────

class TestParamListFallback:

    def test_fallback_scan_colors_header(self, tmp_path):
        cfg_dir = tmp_path / 'share' / 'my_pkg' / 'config'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'dendROS.yaml').write_text(yaml.dump({
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC',
                               'nodes': ['talker']}}
        }))
        stdout, _, _ = run_param_list(str(tmp_path), ['/talker:'])
        assert '\033[' in stdout


# ── ros2 param list /node_name — bare output format ──────────────────────────

class TestParamListNodeArg:
    """When a node path is passed as argv, bare param lines (no header, no indent)
    are colored using that node's color, pre-seeded before reading stdin."""

    def test_bare_params_colored_via_node_arg(self, tmp_path):
        """Bare param names (no header, no indentation) colored when node arg given."""
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time', 'publish_rate'],
                                      node_colors=nc, argv_extra=['/talker'])
        assert '\033[32m\033[2muse_sim_time\033[0m' in stdout
        assert '\033[32m\033[2mpublish_rate\033[0m' in stdout

    def test_bare_params_with_type_flag(self, tmp_path):
        """--param-type type dimming works for bare output."""
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time (bool)'],
                                      node_colors=nc, argv_extra=['/talker'])
        assert '\033[32m\033[2muse_sim_time\033[0m' in stdout
        assert '(\033[2mbool\033[0m)' in stdout

    def test_node_arg_with_namespace(self, tmp_path):
        """Namespaced node path resolved by basename matching."""
        nc = {'color_map': {'talker': '33'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time'],
                                      node_colors=nc, argv_extra=['/my_ns/talker'])
        assert '\033[33m\033[2muse_sim_time\033[0m' in stdout

    def test_node_arg_unmatched_passthrough(self, tmp_path):
        """Unknown node arg leaves bare params uncolored."""
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time'],
                                      node_colors=nc, argv_extra=['/unknown_node'])
        assert_segment_uncolored(stdout, 'use_sim_time')

    def test_node_arg_unmatched_dim(self, tmp_path):
        """dim_unmatched applies to bare params from an unmatched node arg."""
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time'],
                                      node_colors=nc, argv_extra=['/unknown_node'],
                                      global_cfg={'dim_unmatched': True})
        assert '\033[2muse_sim_time\033[0m' in stdout

    def test_node_arg_unmatched_color(self, tmp_path):
        """unmatched_color pre-seeds bare params from an unmatched node arg."""
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time'],
                                      node_colors=nc, argv_extra=['/unknown_node'],
                                      global_cfg={'unmatched_color': 'cyan'})
        assert '\033[' in stdout

    def test_header_in_output_overrides_node_arg(self, tmp_path):
        """When output includes a node header, header color wins (even if arg differs)."""
        nc = {'color_map': {'talker': '32', 'listener': '34'},
              'tag_map': {'talker': '', 'listener': ''}, 'style_map': {}}
        # arg says /talker but output has /listener: header — listener color should apply
        stdout, _, _ = run_param_list(str(tmp_path), ['/listener:', '  p1'],
                                      node_colors=nc, argv_extra=['/talker'])
        assert '\033[34m\033[2mp1\033[0m' in stdout

    def test_flag_args_ignored_for_node_detection(self, tmp_path):
        """Flags like --param-type passed in argv_extra do not confuse node detection."""
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time (bool)'],
                                      node_colors=nc,
                                      argv_extra=['--param-type', '/talker'])
        assert '\033[32m\033[2muse_sim_time\033[0m' in stdout

    def test_no_node_arg_bare_params_passthrough(self, tmp_path):
        """Without a node arg, bare param names are passed through without color."""
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_param_list(str(tmp_path), ['use_sim_time'], node_colors=nc)
        assert_segment_uncolored(stdout, 'use_sim_time')
