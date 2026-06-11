"""Tests for resolve_node and extract_package_name."""
import pytest
from dendROS_pipe import resolve_node, extract_package_name


# ── resolve_node ──────────────────────────────────────────────────────────────

class TestResolveNode:
    def test_exact_match(self):
        color_map = {'talker': '34', 'listener': '33'}
        tag_map   = {'talker': 'TALK', 'listener': 'LIST'}
        assert resolve_node('talker', color_map, tag_map) == ('34', 'TALK')

    def test_exact_match_second_node(self):
        color_map = {'talker': '34', 'listener': '33'}
        tag_map   = {'talker': 'TALK', 'listener': 'LIST'}
        assert resolve_node('listener', color_map, tag_map) == ('33', 'LIST')

    def test_unmatched_returns_none_none(self):
        assert resolve_node('unknown', {}, {}) == (None, None)

    def test_namespace_falls_back_to_basename(self):
        color_map = {'talker': '34'}
        tag_map   = {'talker': 'TALK'}
        assert resolve_node('/my_ns/talker', color_map, tag_map) == ('34', 'TALK')

    def test_deep_namespace_falls_back_to_basename(self):
        color_map = {'talker': '34'}
        tag_map   = {'talker': 'TALK'}
        assert resolve_node('/a/b/c/talker', color_map, tag_map) == ('34', 'TALK')

    def test_full_namespace_path_wins_over_basename(self):
        color_map = {'talker': '34', '/my_ns/talker': '35'}
        tag_map   = {'talker': 'TALK', '/my_ns/talker': 'NS'}
        assert resolve_node('/my_ns/talker', color_map, tag_map) == ('35', 'NS')

    def test_basename_match_when_full_not_in_map(self):
        color_map = {'talker': '34'}
        tag_map   = {'talker': 'TALK'}
        assert resolve_node('/other_ns/talker', color_map, tag_map) == ('34', 'TALK')

    def test_different_basenames_do_not_collide(self):
        color_map = {'talker': '34', 'listener': '33'}
        tag_map   = {'talker': 'TALK', 'listener': 'LIST'}
        code, label = resolve_node('/ns/listener', color_map, tag_map)
        assert code == '33'
        assert label == 'LIST'

    def test_no_namespace_exact_match(self):
        color_map = {'/robot/talker': '35'}
        tag_map   = {'/robot/talker': 'NS'}
        # Plain 'talker' without namespace should NOT match '/robot/talker'
        assert resolve_node('talker', color_map, tag_map) == (None, None)

    def test_tag_map_missing_key_returns_none_label(self):
        color_map = {'talker': '34'}
        tag_map   = {}
        code, label = resolve_node('talker', color_map, tag_map)
        assert code == '34'
        assert label is None

    def test_empty_maps(self):
        assert resolve_node('anything', {}, {}) == (None, None)


# ── extract_package_name ──────────────────────────────────────────────────────

class TestExtractPackageName:
    def test_launch_basic(self):
        assert extract_package_name(['launch', 'my_pkg', 'my_launch.py']) == 'my_pkg'

    def test_run_basic(self):
        assert extract_package_name(['run', 'my_pkg', 'my_node']) == 'my_pkg'

    def test_skips_leading_flags(self):
        assert extract_package_name(['launch', '--debug', 'my_pkg', 'f.py']) == 'my_pkg'

    def test_skips_multiple_flags(self):
        assert extract_package_name(['launch', '-x', '--verbose', 'my_pkg', 'f.py']) == 'my_pkg'

    def test_all_flags_returns_none(self):
        assert extract_package_name(['launch', '--flag1', '--flag2']) is None

    def test_empty_argv(self):
        assert extract_package_name([]) is None

    def test_single_subcommand_only(self):
        assert extract_package_name(['launch']) is None

    def test_underscore_in_package_name(self):
        assert extract_package_name(['launch', 'my_cool_pkg', 'f.py']) == 'my_cool_pkg'

    def test_hyphenated_package_name(self):
        assert extract_package_name(['run', 'my-pkg', 'node']) == 'my-pkg'

    def test_first_positional_not_flag(self):
        # The first non-flag arg is returned even if it looks odd
        assert extract_package_name(['launch', 'pkg', '--some-flag', 'file.py']) == 'pkg'
