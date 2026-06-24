"""Tests for dendros_topic_list.py colorization."""

import json
import os
import sys
import subprocess

import pytest
import yaml

REPO_ROOT       = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TOPIC_LIST_PATH = os.path.join(REPO_ROOT, 'dendROS', 'dendros_topic_list.py')

from conftest import assert_segment_colored, assert_segment_uncolored, colored_segments, strip_ansi


# ── Helper ────────────────────────────────────────────────────────────────────

def run_topic_list(tmp_prefix, topics, global_cfg=None, node_colors=None,
                   pub_nodes=None, sub_nodes=None, timeout=10):
    """Run dendros_topic_list.py with topic names as stdin; return (stdout, stderr, rc)."""
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

    if pub_nodes is not None:
        env['DENDROS_TOPIC_PUBLISHERS'] = json.dumps(pub_nodes)
    if sub_nodes is not None:
        env['DENDROS_TOPIC_SUBSCRIBERS'] = json.dumps(sub_nodes)

    stdin = '\n'.join(topics) + '\n'
    result = subprocess.run(
        [sys.executable, TOPIC_LIST_PATH],
        input=stdin.encode(),
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return result.stdout.decode(), result.stderr.decode(), result.returncode


def _line_for(stdout, topic):
    """Return the output line containing `topic`."""
    return next(l for l in stdout.splitlines() if topic in l)


def _name_col(line, topic):
    """Column of `topic` in the plain-text version of `line`."""
    return strip_ansi(line).index(topic)


# ── Publisher color resolution ────────────────────────────────────────────────

class TestTopicListPublisherColor:
    """Topic is colored with the primary publisher node's group color."""

    def test_topic_colored_by_publisher(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        assert_segment_colored(stdout, '/chatter', '32')

    def test_no_publisher_no_color(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': []},
                                      sub_nodes={'/chatter': []})
        assert_segment_uncolored(stdout, '/chatter')

    def test_primary_publisher_wins_color(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'other': '33'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker', 'other']},
                                      sub_nodes={'/chatter': []})
        assert_segment_colored(stdout, '/chatter', '32')

    def test_wildcard_publisher_color(self, tmp_path):
        nc = {'color_map': {'nav2_*': '35'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/plan'],
                                      node_colors=nc,
                                      pub_nodes={'/plan': ['nav2_planner']},
                                      sub_nodes={'/plan': []})
        assert_segment_colored(stdout, '/plan', '35')

    def test_empty_lines_preserved(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter', '', '/other'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker'], '/other': []},
                                      sub_nodes={'/chatter': [], '/other': []})
        assert '' in stdout.splitlines()

    def test_output_indented(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        for line in stdout.splitlines():
            if line:
                assert line.startswith('  '), f"Expected 2-space indent, got: {line!r}"


# ── Column alignment ──────────────────────────────────────────────────────────

class TestTopicListAlignment:
    """Topic names start at the same column regardless of pub block count."""

    def test_names_aligned_across_different_pub_counts(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'nav2_*': '34'},
              'tag_map': {}, 'style_map': {}}
        # /chatter: 1 pub group → 1 block; /plan: 2 pub groups → "1 1"
        stdout, _, _ = run_topic_list(
            str(tmp_path), ['/chatter', '/plan'],
            node_colors=nc,
            pub_nodes={'/chatter': ['talker'],
                       '/plan':    ['nav2_planner', 'talker']},
            sub_nodes={'/chatter': [], '/plan': []},
        )
        col_chatter = _name_col(_line_for(stdout, '/chatter'), '/chatter')
        col_plan    = _name_col(_line_for(stdout, '/plan'),    '/plan')
        assert col_chatter == col_plan

    def test_sub_blocks_aligned_across_lines(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'listener': '33'},
              'tag_map': {}, 'style_map': {}}
        # /chatter: short name; /longer_topic: long name — subs still start at same column
        stdout, _, _ = run_topic_list(
            str(tmp_path), ['/chatter', '/longer_topic'],
            node_colors=nc,
            pub_nodes={'/chatter':      ['talker'],
                       '/longer_topic': ['talker']},
            sub_nodes={'/chatter':      ['listener'],
                       '/longer_topic': ['listener']},
        )
        # Find the byte offset of the sub block in each plain-text line
        def sub_col(line):
            plain = strip_ansi(line)
            # sub block follows the topic name; find the digit after topic+padding
            topic_end = plain.rstrip().rfind('1')  # count block digit
            return topic_end

        chatter_sub = sub_col(_line_for(stdout, '/chatter'))
        longer_sub  = sub_col(_line_for(stdout, '/longer_topic'))
        assert chatter_sub == longer_sub

    def test_system_topic_name_at_same_column_as_others(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(
            str(tmp_path), ['/chatter', '/parameter_events'],
            node_colors=nc,
            pub_nodes={'/chatter': ['talker']},
            sub_nodes={'/chatter': []},
        )
        col_chatter = _name_col(_line_for(stdout, '/chatter'), '/chatter')
        col_pe      = _name_col(_line_for(stdout, '/parameter_events'), '/parameter_events')
        assert col_chatter == col_pe

    def test_no_pub_topic_name_at_same_column(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        # /scan has pubs, /cmd_vel has none — both names should start at same column
        stdout, _, _ = run_topic_list(
            str(tmp_path), ['/scan', '/cmd_vel'],
            node_colors=nc,
            pub_nodes={'/scan': ['talker'], '/cmd_vel': []},
            sub_nodes={'/scan': [], '/cmd_vel': []},
        )
        col_scan    = _name_col(_line_for(stdout, '/scan'),    '/scan')
        col_cmd_vel = _name_col(_line_for(stdout, '/cmd_vel'), '/cmd_vel')
        assert col_scan == col_cmd_vel


# ── System topics ─────────────────────────────────────────────────────────────

class TestSystemTopics:
    """/parameter_events and /rosout shown plain — no color, tag, or count blocks."""

    def test_parameter_events_no_ansi(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path),
                                      ['/chatter', '/parameter_events'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        pe_line = _line_for(stdout, '/parameter_events')
        assert '\033[' not in pe_line

    def test_rosout_no_ansi(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter', '/rosout'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        rosout_line = _line_for(stdout, '/rosout')
        assert '\033[' not in rosout_line

    def test_system_topic_no_tag(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/parameter_events'],
                                      node_colors=nc,
                                      pub_nodes={}, sub_nodes={})
        assert '[TLK]' not in stdout

    def test_system_topic_no_count_blocks(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        # System topics are excluded from graph queries; no count blocks appear
        stdout, _, _ = run_topic_list(str(tmp_path), ['/rosout'],
                                      node_colors=nc,
                                      pub_nodes={}, sub_nodes={})
        assert ';7m' not in stdout

    def test_system_topic_still_appears(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter', '/rosout'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        assert '/rosout' in stdout

    def test_system_topic_indented(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/parameter_events'],
                                      node_colors=nc,
                                      pub_nodes={}, sub_nodes={})
        pe_line = _line_for(stdout, '/parameter_events')
        assert pe_line.startswith('  ')

    def test_system_topic_type_dimmed_with_t_flag(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        line = '/parameter_events [rcl_interfaces/msg/ParameterEvent]'
        stdout, _, _ = run_topic_list(str(tmp_path), [line],
                                      node_colors=nc,
                                      pub_nodes={}, sub_nodes={})
        # Type should still be dim even for system topics
        assert '[\033[2mrcl_interfaces/msg/ParameterEvent\033[0m]' in stdout
        # But the topic name itself has no color code
        pe_line = _line_for(stdout, '/parameter_events')
        assert not pe_line.startswith('\033[')


# ── Count indicators ──────────────────────────────────────────────────────────

class TestTopicListCounts:
    """Publisher count blocks on left; subscriber count blocks on right."""

    def test_single_pub_block_on_left(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        pub_block = '\033[32;7m1\033[0m'
        assert pub_block in stdout
        assert stdout.index(pub_block) < stdout.index('\033[32m/chatter\033[0m')

    def test_single_sub_block_on_right(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'listener': '33'},
              'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': ['listener']})
        sub_block = '\033[33;7m1\033[0m'
        assert sub_block in stdout
        assert stdout.index('\033[32m/chatter\033[0m') < stdout.index(sub_block)

    def test_multiple_pub_same_group_summed(self, tmp_path):
        nc = {'color_map': {'talker*': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker', 'talker2']},
                                      sub_nodes={'/chatter': []})
        assert '\033[32;7m2\033[0m' in stdout

    def test_multiple_pub_different_groups(self, tmp_path):
        nc = {'color_map': {'loc_node': '34', 'nav_node': '35'},
              'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/scan'],
                                      node_colors=nc,
                                      pub_nodes={'/scan': ['loc_node', 'nav_node']},
                                      sub_nodes={'/scan': []})
        assert '\033[34;7m1\033[0m' in stdout
        assert '\033[35;7m1\033[0m' in stdout

    def test_multiple_sub_different_groups(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'loc': '34', 'nav': '35'},
              'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/scan'],
                                      node_colors=nc,
                                      pub_nodes={'/scan': ['talker']},
                                      sub_nodes={'/scan': ['loc', 'nav']})
        assert '\033[34;7m1\033[0m' in stdout
        assert '\033[35;7m1\033[0m' in stdout

    def test_no_sub_no_trailing_blocks(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        line  = _line_for(stdout, '/chatter')
        plain = strip_ansi(line)
        after = plain[plain.index('/chatter') + len('/chatter'):]
        assert after.strip() == ''

    def test_unmatched_publisher_no_pub_block(self, tmp_path):
        nc = {'color_map': {'known': '34'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['unknown_publisher']},
                                      sub_nodes={'/chatter': []})
        assert ';7m' not in stdout


# ── Tag badge ─────────────────────────────────────────────────────────────────

class TestTopicListTag:
    """Tag badge appears between pub count blocks and the topic name."""

    def test_tag_shown_left_of_topic(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        assert '[TLK]' in stdout
        line = _line_for(stdout, '/chatter')
        assert line.index('[TLK]') < line.index('/chatter')

    def test_tag_between_pub_block_and_topic(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        pub_block    = '\033[32;7m1\033[0m'
        topic_colored = '\033[32m/chatter\033[0m'
        assert pub_block in stdout
        assert stdout.index(pub_block) < stdout.index('[TLK]')
        assert stdout.index('[TLK]') < stdout.index(topic_colored)

    def test_tag_hidden_when_show_tag_cli_false(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []},
                                      global_cfg={'show_tag_cli': False})
        assert '[TLK]' not in stdout

    def test_inverted_tag_style(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'},
              'style_map': {'talker': 'inverted'}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        assert '\033[32;7m[TLK]' in stdout

    def test_empty_label_no_badge(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': ''}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        assert '[]' not in strip_ansi(stdout)

    def test_unmatched_tag(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': []},
                                      sub_nodes={'/chatter': []},
                                      global_cfg={'unmatched_color': 'white',
                                                  'unmatched_tag': '?'})
        assert '[?]' in stdout

    def test_tag_width_counted_in_alignment(self, tmp_path):
        """Badge width is included in mid column, so sub blocks stay aligned."""
        nc = {'color_map': {'talker': '32'}, 'tag_map': {'talker': 'TLK'}, 'style_map': {}}
        stdout, _, _ = run_topic_list(
            str(tmp_path), ['/chatter', '/scan'],
            node_colors=nc,
            pub_nodes={'/chatter': ['talker'], '/scan': ['talker']},
            sub_nodes={'/chatter': ['talker'],  '/scan': ['talker']},
        )
        chatter_sub = strip_ansi(_line_for(stdout, '/chatter')).rstrip().rfind('1')
        scan_sub    = strip_ansi(_line_for(stdout, '/scan')).rstrip().rfind('1')
        assert chatter_sub == scan_sub


# ── -t flag: type annotation dimmed ──────────────────────────────────────────

class TestTopicListTypeFlag:

    def test_type_dimmed_matched_topic(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        line = '/chatter [std_msgs/msg/String]'
        stdout, _, _ = run_topic_list(str(tmp_path), [line],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        assert_segment_colored(stdout, '/chatter', '32')
        assert '[\033[2mstd_msgs/msg/String\033[0m]' in stdout

    def test_type_dimmed_unmatched_topic(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        line = '/unknown [std_msgs/msg/String]'
        stdout, _, _ = run_topic_list(str(tmp_path), [line],
                                      node_colors=nc,
                                      pub_nodes={'/unknown': []},
                                      sub_nodes={'/unknown': []})
        assert '[\033[2mstd_msgs/msg/String\033[0m]' in stdout

    def test_type_not_colored_with_node_color(self, tmp_path):
        nc = {'color_map': {'talker': '32'}, 'tag_map': {}, 'style_map': {}}
        line = '/chatter [std_msgs/msg/String]'
        stdout, _, _ = run_topic_list(str(tmp_path), [line],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': []})
        assert '\033[32mstd_msgs' not in stdout

    def test_sub_blocks_after_type(self, tmp_path):
        nc = {'color_map': {'talker': '32', 'listener': '33'}, 'tag_map': {}, 'style_map': {}}
        line = '/chatter [std_msgs/msg/String]'
        stdout, _, _ = run_topic_list(str(tmp_path), [line],
                                      node_colors=nc,
                                      pub_nodes={'/chatter': ['talker']},
                                      sub_nodes={'/chatter': ['listener']})
        type_bracket = '[\033[2mstd_msgs/msg/String\033[0m]'
        sub_block    = '\033[33;7m1\033[0m'
        assert stdout.index(type_bracket) < stdout.index(sub_block)


# ── Unmatched / dim_unmatched ─────────────────────────────────────────────────

class TestTopicListUnmatched:

    def test_unmatched_color_applied(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/unknown'],
                                      node_colors=nc,
                                      pub_nodes={'/unknown': []},
                                      sub_nodes={'/unknown': []},
                                      global_cfg={'unmatched_color': 'cyan'})
        assert '\033[' in stdout

    def test_dim_unmatched(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/unknown'],
                                      node_colors=nc,
                                      pub_nodes={'/unknown': []},
                                      sub_nodes={'/unknown': []},
                                      global_cfg={'dim_unmatched': True})
        assert '\033[2m/unknown\033[0m' in stdout

    def test_passthrough_when_no_match(self, tmp_path):
        nc = {'color_map': {'known': '34'}, 'tag_map': {}, 'style_map': {}}
        stdout, _, _ = run_topic_list(str(tmp_path), ['/unknown'],
                                      node_colors=nc,
                                      pub_nodes={'/unknown': []},
                                      sub_nodes={'/unknown': []})
        assert_segment_uncolored(stdout, '/unknown')

    def test_passthrough_no_config(self, tmp_path):
        stdout, _, _ = run_topic_list(str(tmp_path), ['/chatter'],
                                      pub_nodes={'/chatter': []},
                                      sub_nodes={'/chatter': []})
        assert '/chatter' in stdout
        assert '\033[' not in stdout

    def test_dim_unmatched_with_type(self, tmp_path):
        nc = {'color_map': {}, 'tag_map': {}, 'style_map': {}}
        line = '/unknown [std_msgs/msg/String]'
        stdout, _, _ = run_topic_list(str(tmp_path), [line],
                                      node_colors=nc,
                                      pub_nodes={'/unknown': []},
                                      sub_nodes={'/unknown': []},
                                      global_cfg={'dim_unmatched': True})
        assert '\033[2m/unknown\033[0m' in stdout
        assert '[\033[2mstd_msgs/msg/String\033[0m]' in stdout


# ── AMENT_PREFIX_PATH fallback ────────────────────────────────────────────────

class TestTopicListFallback:

    def test_fallback_scan_loads_config(self, tmp_path):
        cfg_dir = tmp_path / 'share' / 'my_pkg' / 'config'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'dendROS.yaml').write_text(yaml.dump({
            'groups': {'loc': {'color': 'bold blue', 'label': 'LOC', 'nodes': ['amcl']}}
        }))
        stdout, _, _ = run_topic_list(str(tmp_path), ['/scan'],
                                      pub_nodes={'/scan': ['amcl']},
                                      sub_nodes={'/scan': []})
        assert '\033[' in stdout
