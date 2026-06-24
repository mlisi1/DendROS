"""Tests for dendros_param_describe.py colorization and formatting."""

import os
import sys
import subprocess

import pytest
import yaml

REPO_ROOT          = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
PARAM_DESCRIBE_PATH = os.path.join(REPO_ROOT, 'dendROS', 'dendros_param_describe.py')

from conftest import assert_segment_colored, assert_segment_uncolored, colored_segments, strip_ansi

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SIMPLE = [
    'Parameter name: use_sim_time',
    '  Type: boolean',
    '  Constraints:',
]

_WITH_DESC = [
    'Parameter name: my_param',
    '  Type: string',
    '  Description: Controls the output rate.',
    '  Constraints:',
    '    Read only: true',
]

_MULTI = [
    'Parameter name: use_sim_time',
    '  Type: boolean',
    '  Constraints:',
    'Parameter name: publish_rate',
    '  Type: double',
    '  Description: Rate in Hz.',
    '  Constraints:',
    '    Min value: 0.0',
    '    Max value: 100.0',
    '    Step: 0.0',
]


# ── Helper ────────────────────────────────────────────────────────────────────

def run_describe(tmp_prefix, lines, global_cfg=None, node_colors=None,
                 argv_extra=None, timeout=10):
    """Run dendros_param_describe.py with text lines as stdin."""
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
    cmd = [sys.executable, PARAM_DESCRIBE_PATH] + (argv_extra or [])
    result = subprocess.run(
        cmd, input=stdin.encode(), capture_output=True, env=env, timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


# ── Parameter name header ─────────────────────────────────────────────────────

class TestParamDescribeHeader:
    """'Parameter name: X' line: dim label, bold+node-colored param name."""

    def test_param_name_label_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[2mParameter name:\033[0m' in stdout

    def test_param_name_value_bold_node_color(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[32;1muse_sim_time\033[0m' in stdout

    def test_param_name_unmatched_passthrough(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/unknown'])
        # label still dimmed, name not colored
        assert '\033[2mParameter name:\033[0m' in stdout
        assert '\033[32;1m' not in stdout

    def test_param_name_no_node_arg(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc)
        # no color on param name but label is still formatted
        assert '\033[2mParameter name:\033[0m' in stdout

    def test_namespaced_node_resolved_by_basename(self, tmp_path):
        nc = {'color_map': {'talker': '33'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/my_ns/talker'])
        assert '\033[33;1muse_sim_time\033[0m' in stdout

    def test_wildcard_pattern(self, tmp_path):
        nc = {'color_map': {'nav2_*': '35'}, 'tag_map': {'nav2_*': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/nav2_planner'])
        assert '\033[35;1muse_sim_time\033[0m' in stdout

    def test_multi_param_each_header_colored(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _MULTI, node_colors=nc,
                                    argv_extra=['/talker'])
        headers = [l for l in stdout.splitlines() if 'Parameter name:' in strip_ansi(l)]
        assert len(headers) == 2
        for h in headers:
            assert '\033[32;1m' in h


# ── Field formatting ──────────────────────────────────────────────────────────

class TestParamDescribeFields:
    """Indented field lines: key dimmed, value plain; section headers bold."""

    def test_type_key_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[2mType:\033[0m' in stdout

    def test_type_value_plain(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'])
        type_line = [l for l in stdout.splitlines() if 'Type:' in strip_ansi(l)][0]
        # 'boolean' should appear outside any color code
        segs = colored_segments(type_line)
        assert any('boolean' in t and c is None for t, c in segs)

    def test_description_key_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _WITH_DESC, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[2mDescription:\033[0m' in stdout

    def test_constraints_header_bold(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[1mConstraints:\033[0m' in stdout

    def test_read_only_key_dimmed(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _WITH_DESC, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[2mRead only:\033[0m' in stdout

    def test_range_constraints_formatted(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _MULTI, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[2mMin value:\033[0m' in stdout
        assert '\033[2mMax value:\033[0m' in stdout
        assert '\033[2mStep:\033[0m' in stdout

    def test_formatting_applied_without_node_color(self, tmp_path):
        """Field formatting applies even when the node has no config color."""
        stdout, _, _ = run_describe(str(tmp_path), _WITH_DESC)
        assert '\033[2mType:\033[0m' in stdout
        assert '\033[1mConstraints:\033[0m' in stdout
        assert '\033[2mDescription:\033[0m' in stdout

    def test_indent_preserved(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _WITH_DESC, node_colors=nc,
                                    argv_extra=['/talker'])
        lines = stdout.splitlines()
        type_line = [strip_ansi(l) for l in lines if 'Type:' in strip_ansi(l)][0]
        constraint_line = [strip_ansi(l) for l in lines if 'Read only:' in strip_ansi(l)][0]
        assert type_line.startswith('  ')
        assert constraint_line.startswith('    ')

    def test_empty_lines_preserved(self, tmp_path):
        lines = _SIMPLE + ['', 'Parameter name: other_param', '  Type: integer', '  Constraints:']
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), lines, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '' in stdout.splitlines()


# ── Tag badge ─────────────────────────────────────────────────────────────────

class TestParamDescribeTag:

    def test_tag_shown_before_param_name(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'])
        header = [l for l in stdout.splitlines() if 'Parameter name:' in strip_ansi(l)][0]
        assert '[TLK]' in header
        assert header.index('[TLK]') < header.index('Parameter name:')

    def test_tag_hidden_when_show_tag_cli_false(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'],
                                    global_cfg={'show_tag_cli': False})
        assert '[TLK]' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'},
              'style_map': {'talker': 'inverted'}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/talker'])
        assert '\033[32;7m[TLK]' in stdout

    def test_tag_not_shown_on_field_lines(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _WITH_DESC, node_colors=nc,
                                    argv_extra=['/talker'])
        for line in stdout.splitlines():
            if 'Type:' in strip_ansi(line) or 'Description:' in strip_ansi(line):
                assert '[TLK]' not in line

    def test_unmatched_tag(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/unknown'],
                                    global_cfg={'unmatched_color': 'white', 'unmatched_tag': '?'})
        assert '[?]' in stdout


# ── Unmatched / dim_unmatched ─────────────────────────────────────────────────

class TestParamDescribeUnmatched:

    def test_unmatched_color_applied_to_param_name(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/unknown'],
                                    global_cfg={'unmatched_color': 'cyan'})
        assert '\033[' in stdout
        # at least the param name should be colored
        header = [l for l in stdout.splitlines() if 'Parameter name:' in strip_ansi(l)][0]
        assert '\033[' in header

    def test_dim_unmatched_param_name(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, node_colors=nc,
                                    argv_extra=['/unknown'],
                                    global_cfg={'dim_unmatched': True})
        assert '\033[2muse_sim_time\033[0m' in stdout


# ── AMENT_PREFIX_PATH fallback ────────────────────────────────────────────────

class TestParamDescribeFallback:

    def test_fallback_scan_colors_param_name(self, tmp_path):
        cfg_dir = tmp_path / 'share' / 'my_pkg' / 'config'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'dendROS.yaml').write_text(yaml.dump({
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC',
                               'nodes': ['talker']}}
        }))
        stdout, _, _ = run_describe(str(tmp_path), _SIMPLE, argv_extra=['/talker'])
        assert '\033[' in stdout
