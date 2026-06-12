"""Tests for config merging: launch file parsing and multi-package color map merging."""

import os
import sys
import textwrap

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from dendROS_pipe import (
    extract_launch_file,
    find_launch_file,
    extract_included_packages,
    merge_color_maps,
    resolve_node_mode,
)
from conftest import (
    run_pipe,
    assert_segment_colored,
    assert_segment_uncolored,
)


# ── extract_launch_file ───────────────────────────────────────────────────────

class TestExtractLaunchFile:
    def test_standard(self):
        assert extract_launch_file(['launch', 'my_pkg', 'test.launch.py']) == 'test.launch.py'

    def test_flags_after_launch_file(self):
        # Common usage: ros2 launch my_pkg file.py --ros-args -p foo:=bar
        assert extract_launch_file(['launch', 'my_pkg', 'test.launch.py', '--ros-args', '-p', 'foo:=bar']) == 'test.launch.py'

    def test_flag_between_pkg_and_file(self):
        # Flag value is non-`-` prefixed: treated as positional, consistent with extract_package_name
        result = extract_launch_file(['launch', 'my_pkg', '-d', 'test.launch.py'])
        assert result == 'test.launch.py'

    def test_run_command_returns_none(self):
        assert extract_launch_file(['run', 'my_pkg', 'my_node']) is None

    def test_absolute_path_only_returns_none(self):
        # ros2 launch /abs/path.py — one positional, no file name
        assert extract_launch_file(['launch', '/abs/path/launch.py']) is None

    def test_empty_argv_returns_none(self):
        assert extract_launch_file([]) is None

    def test_only_launch_keyword_returns_none(self):
        assert extract_launch_file(['launch']) is None

    def test_only_pkg_returns_none(self):
        assert extract_launch_file(['launch', 'my_pkg']) is None


# ── extract_included_packages ─────────────────────────────────────────────────

class TestExtractIncludedPackages:
    def test_python_get_package_share_directory(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_text("get_package_share_directory('nav2_bringup')\n")
        assert extract_included_packages(str(f)) == ['nav2_bringup']

    def test_python_find_package_share(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_text("FindPackageShare('slam_toolbox')\n")
        assert extract_included_packages(str(f)) == ['slam_toolbox']

    def test_python_multiple_packages(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_text(textwrap.dedent("""\
            nav2_dir = get_package_share_directory('nav2_bringup')
            slam_dir = get_package_share_directory('slam_toolbox')
        """))
        result = extract_included_packages(str(f))
        assert result == ['nav2_bringup', 'slam_toolbox']

    def test_python_deduplicates(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_text(textwrap.dedent("""\
            d1 = get_package_share_directory('nav2_bringup')
            d2 = get_package_share_directory('nav2_bringup')
        """))
        assert extract_included_packages(str(f)) == ['nav2_bringup']

    def test_python_preserves_order(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_text(textwrap.dedent("""\
            get_package_share_directory('pkg_a')
            get_package_share_directory('pkg_b')
            get_package_share_directory('pkg_c')
        """))
        assert extract_included_packages(str(f)) == ['pkg_a', 'pkg_b', 'pkg_c']

    def test_xml_find_pkg_share(self, tmp_path):
        f = tmp_path / 'test.launch.xml'
        f.write_text(textwrap.dedent("""\
            <launch>
              <include file="$(find-pkg-share nav2_bringup)/launch/bringup.xml"/>
              <include file="$(find-pkg-share slam_toolbox)/launch/online.xml"/>
            </launch>
        """))
        result = extract_included_packages(str(f))
        assert result == ['nav2_bringup', 'slam_toolbox']

    def test_xml_deduplicates(self, tmp_path):
        f = tmp_path / 'test.launch.xml'
        f.write_text(textwrap.dedent("""\
            <launch>
              <include file="$(find-pkg-share nav2_bringup)/launch/a.xml"/>
              <include file="$(find-pkg-share nav2_bringup)/launch/b.xml"/>
            </launch>
        """))
        assert extract_included_packages(str(f)) == ['nav2_bringup']

    def test_nonexistent_file_returns_empty(self):
        assert extract_included_packages('/nonexistent/file.py') == []

    def test_unreadable_content_does_not_raise(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_bytes(b'\xff\xfe invalid utf-8 \x00\x01')
        result = extract_included_packages(str(f))
        assert isinstance(result, list)

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_text('')
        assert extract_included_packages(str(f)) == []

    def test_none_path_returns_empty(self):
        assert extract_included_packages(None) == []


# ── find_launch_file ──────────────────────────────────────────────────────────

class TestFindLaunchFile:
    def test_finds_via_ament_prefix_path(self, tmp_path):
        launch = tmp_path / 'share' / 'my_pkg' / 'launch' / 'test.launch.py'
        launch.parent.mkdir(parents=True)
        launch.write_text('')
        result = find_launch_file.__wrapped__('my_pkg', 'test.launch.py') if hasattr(find_launch_file, '__wrapped__') else None
        # Use environment-based lookup
        os.environ['_TEST_APF'] = str(tmp_path)
        orig = os.environ.get('AMENT_PREFIX_PATH', '')
        os.environ['AMENT_PREFIX_PATH'] = str(tmp_path)
        try:
            result = find_launch_file('my_pkg', 'test.launch.py')
        finally:
            os.environ['AMENT_PREFIX_PATH'] = orig
        assert result == str(launch)

    def test_returns_none_when_not_found(self, tmp_path):
        orig = os.environ.get('AMENT_PREFIX_PATH', '')
        os.environ['AMENT_PREFIX_PATH'] = str(tmp_path)
        try:
            result = find_launch_file('nonexistent_pkg', 'test.launch.py')
        finally:
            os.environ['AMENT_PREFIX_PATH'] = orig
        assert result is None

    def test_returns_none_for_none_args(self):
        assert find_launch_file(None, 'test.launch.py') is None
        assert find_launch_file('my_pkg', None) is None


# ── merge_color_maps ──────────────────────────────────────────────────────────

class TestMergeColorMaps:
    def test_secondary_adds_new_nodes(self):
        merged_c, merged_t, _ = merge_color_maps(
            {'talker': '34'}, {'talker': 'TALK'}, {},
            [({'listener': '32'}, {'listener': 'LIST'}, {})]
        )
        assert merged_c == {'talker': '34', 'listener': '32'}
        assert merged_t == {'talker': 'TALK', 'listener': 'LIST'}

    def test_primary_wins_conflict(self):
        merged_c, merged_t, _ = merge_color_maps(
            {'talker': '34'}, {'talker': 'PRIMARY'}, {},
            [({'talker': '31'}, {'talker': 'SECONDARY'}, {})]
        )
        assert merged_c['talker'] == '34'
        assert merged_t['talker'] == 'PRIMARY'

    def test_empty_primary_uses_secondary(self):
        merged_c, merged_t, _ = merge_color_maps(
            {}, {}, {},
            [({'node1': '31'}, {'node1': 'N1'}, {})]
        )
        assert merged_c == {'node1': '31'}
        assert merged_t == {'node1': 'N1'}

    def test_multiple_secondaries_first_wins(self):
        merged_c, _, _ = merge_color_maps(
            {}, {}, {},
            [
                ({'shared': '32'}, {'shared': 'A'}, {}),
                ({'shared': '31'}, {'shared': 'B'}, {}),
            ]
        )
        assert merged_c['shared'] == '32'

    def test_no_secondaries_returns_copy_of_primary(self):
        primary_c = {'talker': '34'}
        primary_t = {'talker': 'T'}
        merged_c, merged_t, merged_m = merge_color_maps(primary_c, primary_t, {}, [])
        assert merged_c == primary_c
        assert merged_c is not primary_c  # it's a copy
        assert merged_m == {}

    def test_secondary_mode_map_merged_for_new_nodes(self):
        merged_c, _, merged_m = merge_color_maps(
            {'talker': '34'}, {'talker': 'T'}, {},
            [({'listener': '32'}, {'listener': 'L'}, {'listener': 'full_line'})]
        )
        assert merged_m.get('listener') == 'full_line'

    def test_primary_mode_not_overridden_by_secondary(self):
        merged_c, _, merged_m = merge_color_maps(
            {'shared': '34'}, {'shared': 'T'}, {'shared': 'tag_only'},
            [({'shared': '32'}, {'shared': 'S'}, {'shared': 'full_line'})]
        )
        assert merged_m.get('shared') == 'tag_only'

    def test_secondary_mode_not_added_for_conflicting_node(self):
        # shared node exists in primary; its mode_map entry from secondary is ignored
        merged_c, _, merged_m = merge_color_maps(
            {'shared': '34'}, {'shared': 'T'}, {},
            [({'shared': '32'}, {'shared': 'S'}, {'shared': 'full_line'})]
        )
        assert 'shared' not in merged_m


# ── resolve_node_mode ─────────────────────────────────────────────────────────

class TestResolveNodeMode:
    def test_exact_match(self):
        assert resolve_node_mode('talker', {'talker': 'full_line'}) == 'full_line'

    def test_basename_match(self):
        assert resolve_node_mode('/ns/talker', {'talker': 'full_line'}) == 'full_line'

    def test_wildcard_full_path(self):
        assert resolve_node_mode('/ns/nav2_ctrl', {'*/nav2_*': 'full_line'}) == 'full_line'

    def test_wildcard_basename(self):
        assert resolve_node_mode('nav2_controller', {'nav2_*': 'full_line'}) == 'full_line'

    def test_no_match_returns_none(self):
        assert resolve_node_mode('talker', {'listener': 'full_line'}) is None

    def test_empty_mode_map_returns_none(self):
        assert resolve_node_mode('talker', {}) is None


# ── pipeline integration tests ────────────────────────────────────────────────

def _make_pkg(tmp_path, pkg_name, yaml_content, launch_content=None, launch_name='test.launch.py'):
    """Write a dendROS.yaml (and optionally a launch file) into a fake AMENT tree."""
    config_dir = tmp_path / 'share' / pkg_name / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / 'dendROS.yaml').write_text(textwrap.dedent(yaml_content))
    if launch_content is not None:
        launch_dir = tmp_path / 'share' / pkg_name / 'launch'
        launch_dir.mkdir(parents=True, exist_ok=True)
        (launch_dir / launch_name).write_text(textwrap.dedent(launch_content))


class TestConfigMergePipeline:
    def test_secondary_python_nodes_colored(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  """,
                  launch_content="get_package_share_directory('pkg2')\n")
        _make_pkg(tmp_path, 'pkg2',
                  """
                  groups:
                    g2:
                      color: green
                      nodes: [listener]
                  """)

        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[talker-1] [INFO] hello\n', '[listener-1] [INFO] world\n'],
            launch_file='test.launch.py',
        )
        assert_segment_colored(out, '[talker-1]', '34')    # blue
        assert_segment_colored(out, '[listener-1]', '32')  # green

    def test_secondary_xml_nodes_colored(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  """,
                  launch_content='<include file="$(find-pkg-share pkg2)/launch/foo.xml"/>\n',
                  launch_name='test.launch.xml')
        _make_pkg(tmp_path, 'pkg2',
                  """
                  groups:
                    g2:
                      color: green
                      nodes: [listener]
                  """)

        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[talker-1] [INFO] hello\n', '[listener-1] [INFO] world\n'],
            launch_file='test.launch.xml',
        )
        assert_segment_colored(out, '[talker-1]', '34')
        assert_segment_colored(out, '[listener-1]', '32')

    def test_primary_wins_node_conflict(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    primary:
                      color: blue
                      nodes: [shared_node]
                  """,
                  launch_content="get_package_share_directory('pkg2')\n")
        _make_pkg(tmp_path, 'pkg2',
                  """
                  groups:
                    secondary:
                      color: red
                      nodes: [shared_node]
                  """)

        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[shared_node-1] [INFO] msg\n'],
            launch_file='test.launch.py',
        )
        assert_segment_colored(out, '[shared_node-1]', '34')  # blue wins, not red

    def test_no_secondary_config_passes_through(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  """,
                  launch_content="get_package_share_directory('pkg2')\n")
        # pkg2 has no dendROS.yaml

        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[talker-1] [INFO] hello\n', '[listener-1] [INFO] world\n'],
            launch_file='test.launch.py',
        )
        assert_segment_colored(out, '[talker-1]', '34')
        assert_segment_uncolored(out, '[listener-1]')

    def test_self_reference_skipped(self, tmp_path):
        """A launch file referencing its own package must not cause duplicate loading."""
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  """,
                  launch_content="get_package_share_directory('pkg1')\n")

        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[talker-1] [INFO] hello\n'],
            launch_file='test.launch.py',
        )
        assert_segment_colored(out, '[talker-1]', '34')

    def test_config_merge_disabled(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  """,
                  launch_content="get_package_share_directory('pkg2')\n")
        _make_pkg(tmp_path, 'pkg2',
                  """
                  groups:
                    g2:
                      color: green
                      nodes: [listener]
                  """)

        # Write global defaults with config_merge: false under HOME (= ament_prefix = tmp_path)
        global_cfg_dir = tmp_path / '.config' / 'dendROS'
        global_cfg_dir.mkdir(parents=True)
        (global_cfg_dir / 'defaults.yaml').write_text('config_merge: false\n')

        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[talker-1] [INFO] hello\n', '[listener-1] [INFO] world\n'],
            launch_file='test.launch.py',
        )
        assert_segment_colored(out, '[talker-1]', '34')   # primary still works
        assert_segment_uncolored(out, '[listener-1]')     # secondary not merged

    def test_no_launch_file_arg_skips_merge(self, tmp_path):
        """When no launch file is provided in argv, merging is silently skipped."""
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  """)
        _make_pkg(tmp_path, 'pkg2',
                  """
                  groups:
                    g2:
                      color: green
                      nodes: [listener]
                  """)

        # run_pipe without launch_file — argv has no launch file, no merging happens
        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[talker-1] [INFO] hello\n', '[listener-1] [INFO] world\n'],
        )
        assert_segment_colored(out, '[talker-1]', '34')
        assert_segment_uncolored(out, '[listener-1]')


# ── colorize_launch_msgs pipeline tests ───────────────────────────────────────

class TestColorizeLaunchMsgsPipeline:
    def test_launch_msg_colored_by_default(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  """)
        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[INFO] [talker-1]: process started with pid [1234]\n'],
        )
        assert_segment_colored(out, '[talker-1]', '34')

    def test_launch_msg_passes_through_when_disabled(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  defaults:
                    colorize_launch_msgs: false
                  """)
        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[INFO] [talker-1]: process started with pid [1234]\n'],
        )
        assert_segment_uncolored(out, '[talker-1]')

    def test_node_output_still_colored_when_launch_msgs_disabled(self, tmp_path):
        _make_pkg(tmp_path, 'pkg1',
                  """
                  groups:
                    g1:
                      color: blue
                      nodes: [talker]
                  defaults:
                    colorize_launch_msgs: false
                  """)
        out, _, _ = run_pipe(
            str(tmp_path), 'pkg1',
            ['[talker-1] [INFO] hello world\n'],
        )
        assert_segment_colored(out, '[talker-1]', '34')
