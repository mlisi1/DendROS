"""Tests for load_config — all YAML combinations and edge cases."""
import os
import pytest
import yaml
from dendROS_pipe import load_config, _resolve_color

from conftest import CONFIGS_DIR


def fixture_path(name):
    return os.path.join(CONFIGS_DIR, name)


# ── basic.yaml ────────────────────────────────────────────────────────────────

class TestBasicConfig:
    def test_node_in_color_map(self):
        color_map, _, _ = load_config(fixture_path('basic.yaml'))
        assert 'talker' in color_map

    def test_color_resolved_to_ansi_code(self):
        color_map, _, _ = load_config(fixture_path('basic.yaml'))
        assert color_map['talker'] == _resolve_color('blue')

    def test_label_in_tag_map(self):
        _, tag_map, _ = load_config(fixture_path('basic.yaml'))
        assert tag_map['talker'] == 'TALK'

    def test_defaults_color_mode(self):
        _, _, defaults = load_config(fixture_path('basic.yaml'))
        assert defaults.get('color_mode') == 'tag_only'

    def test_defaults_show_tag(self):
        _, _, defaults = load_config(fixture_path('basic.yaml'))
        assert defaults.get('show_group_tag') is True

    def test_defaults_unmatched_null(self):
        _, _, defaults = load_config(fixture_path('basic.yaml'))
        assert defaults.get('unmatched_color') is None


# ── full_line_mode.yaml ───────────────────────────────────────────────────────

class TestFullLineMode:
    def test_color_mode_full_line(self):
        _, _, defaults = load_config(fixture_path('full_line_mode.yaml'))
        assert defaults.get('color_mode') == 'full_line'

    def test_node_still_resolved(self):
        color_map, _, _ = load_config(fixture_path('full_line_mode.yaml'))
        assert 'talker' in color_map


# ── hex_colors.yaml ───────────────────────────────────────────────────────────

class TestHexColorsConfig:
    def test_plain_hex_resolved(self):
        color_map, _, _ = load_config(fixture_path('hex_colors.yaml'))
        assert color_map['node_a'] == '38;2;255;102;0'

    def test_at_bold_hex_resolved(self):
        color_map, _, _ = load_config(fixture_path('hex_colors.yaml'))
        assert color_map['node_b'] == '1;38;2;0;170;255'

    def test_bold_word_hex_resolved(self):
        color_map, _, _ = load_config(fixture_path('hex_colors.yaml'))
        assert color_map['node_c'] == '1;38;2;0;255;68'

    def test_labels_present(self):
        _, tag_map, _ = load_config(fixture_path('hex_colors.yaml'))
        assert tag_map['node_a'] == 'ORG'
        assert tag_map['node_b'] == 'BLU'
        assert tag_map['node_c'] == 'GRN'


# ── raw_ansi.yaml ─────────────────────────────────────────────────────────────

class TestRawAnsiConfig:
    def test_raw_code_unchanged(self):
        color_map, _, _ = load_config(fixture_path('raw_ansi.yaml'))
        assert color_map['raw_node'] == '34;1'

    def test_label_present(self):
        _, tag_map, _ = load_config(fixture_path('raw_ansi.yaml'))
        assert tag_map['raw_node'] == 'RAW'


# ── modifiers.yaml ────────────────────────────────────────────────────────────

class TestModifiersConfig:
    def test_bold_red(self):
        color_map, _, _ = load_config(fixture_path('modifiers.yaml'))
        assert color_map['bold_node'] == '31;1'

    def test_light_blue(self):
        color_map, _, _ = load_config(fixture_path('modifiers.yaml'))
        assert color_map['light_node'] == '94'

    def test_dark_green(self):
        color_map, _, _ = load_config(fixture_path('modifiers.yaml'))
        assert color_map['dark_node'] == '32;2'

    def test_bold_light_cyan(self):
        color_map, _, _ = load_config(fixture_path('modifiers.yaml'))
        assert color_map['boldlight_node'] == '96;1'

    def test_bright_magenta(self):
        color_map, _, _ = load_config(fixture_path('modifiers.yaml'))
        assert color_map['bright_node'] == '95'

    def test_dim_yellow(self):
        color_map, _, _ = load_config(fixture_path('modifiers.yaml'))
        assert color_map['dim_node'] == '33;2'


# ── unmatched_color.yaml ──────────────────────────────────────────────────────

class TestUnmatchedColorConfig:
    def test_known_node_in_map(self):
        color_map, _, _ = load_config(fixture_path('unmatched_color.yaml'))
        assert 'known_node' in color_map

    def test_unmatched_color_set_in_defaults(self):
        _, _, defaults = load_config(fixture_path('unmatched_color.yaml'))
        assert defaults.get('unmatched_color') == 'red'


# ── no_tag.yaml ───────────────────────────────────────────────────────────────

class TestNoTagConfig:
    def test_show_group_tag_false(self):
        _, _, defaults = load_config(fixture_path('no_tag.yaml'))
        assert defaults.get('show_group_tag') is False


# ── multi_group.yaml ──────────────────────────────────────────────────────────

class TestMultiGroupConfig:
    def test_all_six_nodes_present(self):
        color_map, _, _ = load_config(fixture_path('multi_group.yaml'))
        expected = {
            'nav2_controller', 'nav2_planner',
            'slam_toolbox', 'amcl',
            'lidar_driver', 'imu_driver',
        }
        assert set(color_map.keys()) == expected

    def test_nav_group_color(self):
        color_map, _, _ = load_config(fixture_path('multi_group.yaml'))
        nav_code = _resolve_color('bold green')
        assert color_map['nav2_controller'] == nav_code
        assert color_map['nav2_planner'] == nav_code

    def test_loc_group_color(self):
        color_map, _, _ = load_config(fixture_path('multi_group.yaml'))
        loc_code = _resolve_color('bold blue')
        assert color_map['slam_toolbox'] == loc_code
        assert color_map['amcl'] == loc_code

    def test_hw_group_color(self):
        color_map, _, _ = load_config(fixture_path('multi_group.yaml'))
        hw_code = _resolve_color('bold yellow')
        assert color_map['lidar_driver'] == hw_code
        assert color_map['imu_driver'] == hw_code

    def test_group_labels(self):
        _, tag_map, _ = load_config(fixture_path('multi_group.yaml'))
        assert tag_map['nav2_controller'] == 'NAV'
        assert tag_map['slam_toolbox']    == 'LOC'
        assert tag_map['lidar_driver']    == 'HW'

    def test_different_groups_have_different_codes(self):
        color_map, _, _ = load_config(fixture_path('multi_group.yaml'))
        assert color_map['nav2_controller'] != color_map['slam_toolbox']
        assert color_map['slam_toolbox']    != color_map['lidar_driver']


# ── namespace.yaml ────────────────────────────────────────────────────────────

class TestNamespaceConfig:
    def test_full_path_key_in_color_map(self):
        color_map, _, _ = load_config(fixture_path('namespace.yaml'))
        assert '/robot/talker'   in color_map
        assert '/robot/listener' in color_map

    def test_color_resolved(self):
        color_map, _, _ = load_config(fixture_path('namespace.yaml'))
        assert color_map['/robot/talker'] == _resolve_color('magenta')

    def test_label_present(self):
        _, tag_map, _ = load_config(fixture_path('namespace.yaml'))
        assert tag_map['/robot/talker'] == 'NS'


# ── empty_groups.yaml ─────────────────────────────────────────────────────────

class TestEmptyGroupsConfig:
    def test_color_map_empty(self):
        color_map, _, _ = load_config(fixture_path('empty_groups.yaml'))
        assert color_map == {}

    def test_tag_map_empty(self):
        _, tag_map, _ = load_config(fixture_path('empty_groups.yaml'))
        assert tag_map == {}

    def test_defaults_still_returned(self):
        _, _, defaults = load_config(fixture_path('empty_groups.yaml'))
        assert defaults.get('color_mode') == 'tag_only'


# ── Edge cases and error handling ─────────────────────────────────────────────

class TestConfigEdgeCases:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / 'nonexistent.yaml'))

    def test_malformed_yaml_raises(self, tmp_path):
        bad = tmp_path / 'bad.yaml'
        bad.write_text(': : : invalid yaml :\n  - [unclosed')
        with pytest.raises(Exception):
            load_config(str(bad))

    def test_no_groups_key_returns_empty_maps(self, tmp_path):
        cfg = tmp_path / 'no_groups.yaml'
        cfg.write_text('defaults:\n  color_mode: "tag_only"\n')
        color_map, tag_map, _ = load_config(str(cfg))
        assert color_map == {}
        assert tag_map == {}

    def test_node_missing_color_key(self, tmp_path):
        cfg = tmp_path / 'no_color.yaml'
        cfg.write_text(
            'groups:\n'
            '  g:\n'
            '    label: "G"\n'
            '    nodes:\n'
            '      - my_node\n'
        )
        color_map, _, _ = load_config(str(cfg))
        # my_node should be present (empty string color is the current behavior)
        assert 'my_node' in color_map

    def test_node_missing_label_uses_group_name(self, tmp_path):
        cfg = tmp_path / 'no_label.yaml'
        cfg.write_text(
            'groups:\n'
            '  navigation:\n'
            '    color: "blue"\n'
            '    nodes:\n'
            '      - planner\n'
        )
        _, tag_map, _ = load_config(str(cfg))
        # Label defaults to group_name.upper()[:3] → 'NAV'
        assert tag_map['planner'] == 'NAV'

    def test_empty_nodes_list_no_crash(self, tmp_path):
        cfg = tmp_path / 'empty_nodes.yaml'
        cfg.write_text(
            'groups:\n'
            '  g:\n'
            '    color: "blue"\n'
            '    label: "G"\n'
            '    nodes: []\n'
        )
        color_map, tag_map, _ = load_config(str(cfg))
        assert color_map == {}

    def test_null_nodes_no_crash(self, tmp_path):
        cfg = tmp_path / 'null_nodes.yaml'
        cfg.write_text(
            'groups:\n'
            '  g:\n'
            '    color: "blue"\n'
            '    label: "G"\n'
            '    nodes: null\n'
        )
        color_map, _, _ = load_config(str(cfg))
        assert color_map == {}

    def test_multiple_nodes_same_group(self, tmp_path):
        cfg = tmp_path / 'multi_nodes.yaml'
        cfg.write_text(
            'groups:\n'
            '  g:\n'
            '    color: "blue"\n'
            '    label: "G"\n'
            '    nodes:\n'
            '      - node_a\n'
            '      - node_b\n'
            '      - node_c\n'
        )
        color_map, tag_map, _ = load_config(str(cfg))
        assert color_map['node_a'] == color_map['node_b'] == color_map['node_c']
        assert tag_map['node_a'] == tag_map['node_b'] == 'G'

    def test_null_groups_no_crash(self, tmp_path):
        cfg = tmp_path / 'null_groups.yaml'
        cfg.write_text('groups: null\n')
        color_map, tag_map, _ = load_config(str(cfg))
        assert color_map == {}

    def test_null_defaults_returns_empty_dict(self, tmp_path):
        cfg = tmp_path / 'null_defaults.yaml'
        cfg.write_text('defaults: null\n')
        _, _, defaults = load_config(str(cfg))
        assert isinstance(defaults, dict)
