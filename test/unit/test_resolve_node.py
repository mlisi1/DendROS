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


# ── resolve_node — wildcard matching ─────────────────────────────────────────

class TestResolveNodeWildcard:
    def test_wildcard_suffix_matches_node(self):
        color_map = {'nav2_*': '32'}
        tag_map   = {'nav2_*': 'NAV'}
        assert resolve_node('nav2_controller', color_map, tag_map) == ('32', 'NAV')

    def test_wildcard_suffix_matches_second_node(self):
        color_map = {'nav2_*': '32'}
        tag_map   = {'nav2_*': 'NAV'}
        assert resolve_node('nav2_planner', color_map, tag_map) == ('32', 'NAV')

    def test_wildcard_does_not_match_unrelated_node(self):
        color_map = {'nav2_*': '32'}
        tag_map   = {'nav2_*': 'NAV'}
        assert resolve_node('controller', color_map, tag_map) == (None, None)

    def test_wildcard_prefix_pattern_matches_namespaced(self):
        color_map = {'*/amcl': '34'}
        tag_map   = {'*/amcl': 'LOC'}
        assert resolve_node('/robot/amcl', color_map, tag_map) == ('34', 'LOC')

    def test_wildcard_prefix_pattern_matches_deep_namespace(self):
        color_map = {'*/amcl': '34'}
        tag_map   = {'*/amcl': 'LOC'}
        assert resolve_node('/a/b/c/amcl', color_map, tag_map) == ('34', 'LOC')

    def test_exact_full_path_beats_wildcard(self):
        color_map = {'nav2_controller': '31', 'nav2_*': '32'}
        tag_map   = {'nav2_controller': 'CTRL', 'nav2_*': 'NAV'}
        code, label = resolve_node('nav2_controller', color_map, tag_map)
        assert code == '31'
        assert label == 'CTRL'

    def test_exact_basename_beats_wildcard(self):
        color_map = {'nav2_planner': '31', 'nav2_*': '32'}
        tag_map   = {'nav2_planner': 'PLAN', 'nav2_*': 'NAV'}
        code, label = resolve_node('/ns/nav2_planner', color_map, tag_map)
        assert code == '31'
        assert label == 'PLAN'

    def test_wildcard_basename_matches(self):
        color_map = {'nav2_*': '32'}
        tag_map   = {'nav2_*': 'NAV'}
        assert resolve_node('/my_ns/nav2_controller', color_map, tag_map) == ('32', 'NAV')

    def test_first_matching_wildcard_wins(self):
        color_map = {'nav2_*': '32', 'nav*': '33'}
        tag_map   = {'nav2_*': 'NAV2', 'nav*': 'NAV'}
        code, _ = resolve_node('nav2_planner', color_map, tag_map)
        assert code == '32'

    def test_no_wildcard_match_returns_none(self):
        color_map = {'nav2_*': '32'}
        tag_map   = {'nav2_*': 'NAV'}
        assert resolve_node('localization', color_map, tag_map) == (None, None)

    def test_question_mark_wildcard(self):
        color_map = {'node_?': '35'}
        tag_map   = {'node_?': 'N'}
        assert resolve_node('node_a', color_map, tag_map) == ('35', 'N')
        assert resolve_node('node_ab', color_map, tag_map) == (None, None)

    def test_wildcard_star_matches_anything(self):
        color_map = {'*': '36'}
        tag_map   = {'*': 'ALL'}
        assert resolve_node('any_node_name', color_map, tag_map) == ('36', 'ALL')
