"""Tests for dendros_config — data-layer helpers only (no curses)."""

import os
import re
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

import dendros_config as cfg_mod
import lib.global_config as gc_mod
from dendros_config import (
    _DEFAULTS,
    _FIELDS,
    _DESCS,
    _UNCHANGED,
    _val_str,
    _TAB_ORDER,
    _fields_for_tab,
)
from lib.logo import (
    _LOGO_LINES,
    _LOGO_W,
    _LOGO_ROWS,
    _LOGO_PARSED,
    _shift_rgb,
    _render_logo_line,
    _make_title_line,
    build_small_logo,
    _extract_full_pixel_grid,
    _extract_pixel_grid_from_lines,
    _downsample_pixel_grid,
    _HQ_LOGO_W,
    _HQ_LOGO_ROWS,
    _HQ_LOGO_LINES,
    _HQ_PIXEL_GRID,
)
from lib.global_config import load_global_config, save_global_config


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_config(monkeypatch, tmp_path):
    """Redirect GLOBAL_CONFIG_PATH to a temp file for every test."""
    path = str(tmp_path / "defaults.yaml")
    monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", path)
    return path


# ── _val_str ──────────────────────────────────────────────────────────────────

class TestValStr:
    def test_true_displays_on(self):
        assert _val_str(True) == "on"

    def test_false_displays_off(self):
        assert _val_str(False) == "off"

    def test_none_displays_null(self):
        assert _val_str(None) == "null"

    def test_string_passes_through(self):
        assert _val_str("tag_only") == "tag_only"

    def test_arbitrary_string(self):
        assert _val_str("bold blue") == "bold blue"


# ── load_global_config ────────────────────────────────────────────────────────

class TestLoadGlobalConfig:
    def test_returns_defaults_when_no_file(self, tmp_config):
        assert not os.path.exists(tmp_config)
        result = load_global_config()
        assert result == _DEFAULTS

    def test_loads_existing_file(self, tmp_config):
        data = {
            "color_mode": "full_line",
            "show_tag_launch": False,
            "show_tag_cli": False,
            "tag_position": "before",
            "unmatched_color": "bold blue",
            "debug": True,
            "config_merge": False,
            "colorize_launch_msgs": False,
            "unmatched_tag": "?",
            "dim_unmatched": True,
            "init_modify_build": False,
            "init_on_existing": "overwrite",
            "init_color": "null",
            "init_color_bold": True,
            "init_label": True,
            "crash_alert": True,
            "crash_alert_color": "red",
            "crash_alert_interval": 60,
            "traceback_color": "red",
            "tag_style": "inverted",
            "show_default_services": False,
            "topic_sort": "default",
            "param_change_alert": True,
            "param_change_alert_scope": "all",
            "param_change_alert_style": "inverted",
            "show_timestamp": False,
            "show_logger_name": False,
            "launch_mode": "tui",
            "tui_scrollback_lines": 2000,
            "ignore_bold": True,
        }
        with open(tmp_config, "w") as f:
            yaml.dump(data, f)
        result = load_global_config()
        assert result == data

    def test_fills_missing_keys_with_defaults(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"color_mode": "full_line"}, f)
        result = load_global_config()
        assert result["color_mode"] == "full_line"
        assert result["show_tag_launch"] == _DEFAULTS["show_tag_launch"]
        assert result["show_tag_cli"] == _DEFAULTS["show_tag_cli"]
        assert result["show_default_services"] == _DEFAULTS["show_default_services"]
        assert result["unmatched_color"] == _DEFAULTS["unmatched_color"]
        assert result["debug"] == _DEFAULTS["debug"]

    def test_ignores_unknown_keys(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"color_mode": "full_line", "unknown_key": "value"}, f)
        result = load_global_config()
        assert "unknown_key" not in result

    def test_returns_defaults_on_malformed_yaml(self, tmp_config):
        with open(tmp_config, "w") as f:
            f.write(": invalid: yaml: {{")
        result = load_global_config()
        assert result == _DEFAULTS

    def test_null_unmatched_color_loaded_as_none(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"unmatched_color": None}, f)
        result = load_global_config()
        assert result["unmatched_color"] is None

    def test_debug_false_by_default(self, tmp_config):
        result = load_global_config()
        assert result["debug"] is False


# ── save_global_config ────────────────────────────────────────────────────────

class TestSaveGlobalConfig:
    def test_creates_file(self, tmp_config):
        assert not os.path.exists(tmp_config)
        save_global_config(dict(_DEFAULTS))
        assert os.path.exists(tmp_config)

    def test_creates_parent_directory(self, monkeypatch, tmp_path):
        deep_path = str(tmp_path / "a" / "b" / "defaults.yaml")
        monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", deep_path)
        save_global_config(dict(_DEFAULTS))
        assert os.path.exists(deep_path)

    def test_roundtrip_all_defaults(self, tmp_config):
        save_global_config(dict(_DEFAULTS))
        result = load_global_config()
        assert result == _DEFAULTS

    def test_roundtrip_custom_values(self, tmp_config):
        custom = {
            "color_mode": "full_line",
            "show_tag_launch": False,
            "show_tag_cli": False,
            "tag_position": "before",
            "unmatched_color": "#FF6600",
            "debug": True,
            "config_merge": False,
            "colorize_launch_msgs": False,
            "unmatched_tag": "?",
            "dim_unmatched": True,
            "init_modify_build": False,
            "init_on_existing": "overwrite",
            "init_color": "null",
            "init_color_bold": True,
            "init_label": True,
            "crash_alert": True,
            "crash_alert_color": "red",
            "crash_alert_interval": 60,
            "traceback_color": "off",
            "tag_style": "inverted",
            "show_default_services": False,
            "topic_sort": "group",
            "param_change_alert": True,
            "param_change_alert_scope": "all",
            "param_change_alert_style": "inverted",
            "show_timestamp": False,
            "show_logger_name": False,
            "launch_mode": "tui",
            "tui_scrollback_lines": 2000,
            "ignore_bold": True,
        }
        save_global_config(custom)
        result = load_global_config()
        assert result == custom

    def test_saved_yaml_contains_all_keys(self, tmp_config):
        save_global_config(dict(_DEFAULTS))
        with open(tmp_config) as f:
            data = yaml.safe_load(f)
        for k in _DEFAULTS:
            assert k in data

    def test_saves_none_as_yaml_null(self, tmp_config):
        cfg = dict(_DEFAULTS)
        cfg["unmatched_color"] = None
        save_global_config(cfg)
        with open(tmp_config) as f:
            raw = f.read()
        assert "null" in raw

    def test_overwrites_previous_save(self, tmp_config):
        save_global_config({**_DEFAULTS, "color_mode": "tag_only"})
        save_global_config({**_DEFAULTS, "color_mode": "full_line"})
        result = load_global_config()
        assert result["color_mode"] == "full_line"


# ── field definitions ─────────────────────────────────────────────────────────

class TestFieldDefinitions:
    def test_all_defaults_have_a_field(self):
        field_keys = {f[0] for f in _FIELDS}
        for k in _DEFAULTS:
            assert k in field_keys, f"No field entry for default key '{k}'"

    def test_all_cycle_fields_have_options(self):
        for f in _FIELDS:
            if f.kind == "cycle":
                assert f.opts is not None and len(f.opts) >= 2, (
                    f"Cycle field '{f.key}' needs at least 2 options"
                )

    def test_all_fields_have_descriptions(self):
        for f in _FIELDS:
            assert f.key in _DESCS, f"No description for field '{f.key}'"
            assert len(_DESCS[f.key]) >= 1

    def test_cycle_options_include_default_value(self):
        """Every default value must appear as a cycle option for its field."""
        for f in _FIELDS:
            if f.kind != "cycle":
                continue
            default = _DEFAULTS[f.key]
            opt_strs = [str(o) for o in f.opts]
            assert str(default) in opt_strs, (
                f"Default '{default}' for '{f.key}' not in cycle options {f.opts}"
            )


# ── tab grouping ──────────────────────────────────────────────────────────────

class TestTabGrouping:
    def test_every_field_has_a_declared_group(self):
        tab_ids = {tid for tid, _ in _TAB_ORDER}
        for f in _FIELDS:
            assert f.group in tab_ids, f"Field '{f.key}' has undeclared group '{f.group}'"

    def test_every_declared_tab_has_at_least_one_field(self):
        for tid, label in _TAB_ORDER:
            assert len(_fields_for_tab(tid)) >= 1, f"Tab '{tid}' ({label}) has no fields"

    def test_no_duplicate_tab_ids(self):
        ids = [tid for tid, _ in _TAB_ORDER]
        assert len(ids) == len(set(ids))

    def test_tab_field_counts_sum_to_total_field_count(self):
        total = sum(len(_fields_for_tab(tid)) for tid, _ in _TAB_ORDER)
        assert total == len(_FIELDS)

    def test_fields_for_tab_preserves_fields_declaration_order(self):
        output_fields = _fields_for_tab("output")
        assert output_fields[0].key == "color_mode"
        assert output_fields[-1].key == "ignore_bold"

    def test_field_is_namedtuple_with_group_attribute(self):
        assert hasattr(_FIELDS[0], "group")
        assert isinstance(_FIELDS[0], tuple)

    def test_field_positional_indexing_still_works(self):
        # group is appended, not inserted, so f[0..3] must remain
        # (key, label, kind, opts) for backward compatibility.
        f = _FIELDS[0]
        assert f[0] == f.key and f[1] == f.label and f[2] == f.kind and f[3] == f.opts


# ── logo data integrity ───────────────────────────────────────────────────────

class TestLogoData:
    def test_logo_lines_has_correct_row_count(self):
        assert len(_LOGO_LINES) == _LOGO_ROWS

    def test_logo_w_is_positive(self):
        assert _LOGO_W > 0

    def test_logo_rows_is_positive(self):
        assert _LOGO_ROWS > 0

    def test_logo_lines_are_strings(self):
        for i, line in enumerate(_LOGO_LINES):
            assert isinstance(line, str), f"Logo line {i} is not a string: {type(line)}"

    def test_logo_lines_contain_ansi_escapes(self):
        combined = ''.join(_LOGO_LINES)
        assert '\x1b[' in combined, "Logo lines must contain ANSI escape codes"

    def test_logo_lines_visible_chars_are_printable(self):
        import re
        ansi_re = re.compile(r'\x1b\[[0-9;]*m')
        for i, line in enumerate(_LOGO_LINES):
            stripped = ansi_re.sub('', line)
            for ch in stripped:
                assert ch.isprintable(), (
                    f"Logo line {i} contains non-printable char {ch!r} (U+{ord(ch):04X})"
                )

    def test_logo_lines_no_wrong_unicode(self):
        for i, line in enumerate(_LOGO_LINES):
            assert '◄' not in line, f"Logo line {i} contains wrong char ◄ (U+25C4)"
            assert '►' not in line, f"Logo line {i} contains wrong char ► (U+25BA)"


# ── logo animation helpers ────────────────────────────────────────────────────

class TestLogoAnimation:
    def test_parsed_has_correct_line_count(self):
        assert len(_LOGO_PARSED) == _LOGO_ROWS

    def test_parsed_lines_are_lists(self):
        for i, segs in enumerate(_LOGO_PARSED):
            assert isinstance(segs, list), f"Parsed line {i} is not a list"

    def test_parsed_segments_are_tuples(self):
        for segs in _LOGO_PARSED:
            for seg in segs:
                assert len(seg) == 3

    def test_shift_rgb_none_returns_none(self):
        assert _shift_rgb(None, 0.5) is None

    def test_shift_rgb_zero_offset_returns_same(self):
        assert _shift_rgb((224, 127, 0), 0.0) == (224, 127, 0)

    def test_shift_rgb_grey_unchanged(self):
        # Pure grey has saturation 0 — should not be altered
        assert _shift_rgb((100, 100, 100), 0.5) == (100, 100, 100)

    def test_shift_rgb_black_unchanged(self):
        assert _shift_rgb((0, 0, 0), 0.5) == (0, 0, 0)

    def test_shift_rgb_saturated_changes(self):
        # Orange (224, 127, 0) has high saturation — shifting by 0.5 produces a different color
        shifted = _shift_rgb((224, 127, 0), 0.5)
        assert shifted != (224, 127, 0)

    def test_shift_rgb_full_cycle_returns_same(self):
        # Shifting by exactly 1.0 is a full hue cycle — same color
        rgb = (224, 127, 0)
        shifted = _shift_rgb(rgb, 1.0)
        # round-trip through float may differ by ±1
        assert all(abs(shifted[i] - rgb[i]) <= 1 for i in range(3))

    def test_render_logo_line_returns_string(self):
        for segs in _LOGO_PARSED:
            result = _render_logo_line(segs, 0.0)
            assert isinstance(result, str)

    def test_render_logo_line_zero_offset_has_ansi(self):
        # At least some lines have colored pixels
        colored_lines = [
            segs for segs in _LOGO_PARSED
            if any(fg or bg for _, fg, bg in segs)
        ]
        assert len(colored_lines) > 0
        for segs in colored_lines:
            result = _render_logo_line(segs, 0.0)
            assert '\x1b[' in result

    def test_render_logo_line_shifted_differs(self):
        # A line with colored pixels rendered at offset 0.5 must differ from offset 0.0
        for segs in _LOGO_PARSED:
            if any(fg and sum(fg) > 0 for _, fg, _ in segs):
                assert _render_logo_line(segs, 0.5) != _render_logo_line(segs, 0.0)
                break

    def test_make_title_line_returns_string(self):
        assert isinstance(_make_title_line(0.0), str)

    def test_make_title_line_contains_dend_ros(self):
        title = _make_title_line(0.0)
        assert 'D e n d' in title
        assert 'R O S' in title

    def test_make_title_line_shifted_differs(self):
        assert _make_title_line(0.0) != _make_title_line(0.5)

    def test_make_title_line_has_ansi(self):
        assert '\x1b[' in _make_title_line(0.0)


# ── small (downsampled) logo — used in the launch TUI's header ────────────────

class TestFullPixelGrid:
    def test_dimensions(self):
        grid = _extract_full_pixel_grid()
        assert len(grid) == 2 * _LOGO_ROWS
        assert all(len(row) == _LOGO_W for row in grid)

    def test_contains_some_non_none_pixels(self):
        grid = _extract_full_pixel_grid()
        assert any(cell is not None for row in grid for cell in row)

    def test_non_none_pixels_are_rgb_triples(self):
        grid = _extract_full_pixel_grid()
        for row in grid:
            for cell in row:
                if cell is not None:
                    assert len(cell) == 3
                    assert all(isinstance(c, int) for c in cell)


class TestDownsamplePixelGrid:
    def test_output_dimensions(self):
        grid = [[(1, 2, 3)] * 10 for _ in range(10)]
        out = _downsample_pixel_grid(grid, 4, 4)
        assert len(out) == 4
        assert all(len(row) == 4 for row in out)

    def test_all_none_block_stays_none(self):
        grid = [[None] * 4 for _ in range(4)]
        out = _downsample_pixel_grid(grid, 2, 2)
        assert all(cell is None for row in out for cell in row)

    def test_uniform_color_survives_downsampling(self):
        grid = [[(10, 20, 30)] * 4 for _ in range(4)]
        out = _downsample_pixel_grid(grid, 2, 2)
        assert all(cell == (10, 20, 30) for row in out for cell in row)

    def test_averages_mixed_colors(self):
        grid = [[(0, 0, 0), (100, 100, 100)], [(0, 0, 0), (100, 100, 100)]]
        out = _downsample_pixel_grid(grid, 1, 1)
        assert out[0][0] == (50, 50, 50)


class TestBuildSmallLogo:
    def test_default_row_count(self):
        lines = build_small_logo()
        assert len(lines) == 4

    def test_custom_row_count(self):
        lines = build_small_logo(target_rows=2)
        assert len(lines) == 2

    def test_lines_are_strings(self):
        for line in build_small_logo(3):
            assert isinstance(line, str)

    def test_contains_ansi(self):
        combined = ''.join(build_small_logo(3))
        assert '\x1b[' in combined

    def test_does_not_crash_for_various_sizes(self):
        for n in (1, 2, 3, 4, 5, 8):
            lines = build_small_logo(n)
            assert len(lines) == n

    def test_custom_target_cols(self):
        lines = build_small_logo(target_rows=2, target_cols=5)
        for line in lines:
            visible = re.sub(r'\x1b\[[0-9;]*m', '', line)
            assert len(visible) == 5


class TestHqLogoSource:
    """The higher-fidelity 84x84 source (from docs/assets/images/dendros_small.png,
    decoded offline via stdlib zlib/struct — no PIL/third-party dep) that
    build_small_logo() downsamples from, instead of re-shrinking the already-low-res
    42x21 _LOGO_LINES."""

    def test_dimensions(self):
        assert _HQ_LOGO_W == 84
        assert _HQ_LOGO_ROWS == 42
        assert len(_HQ_LOGO_LINES) == _HQ_LOGO_ROWS

    def test_lines_are_strings(self):
        for line in _HQ_LOGO_LINES:
            assert isinstance(line, str)

    def test_contains_ansi(self):
        assert '\x1b[' in ''.join(_HQ_LOGO_LINES)

    def test_pixel_grid_dimensions(self):
        assert len(_HQ_PIXEL_GRID) == 2 * _HQ_LOGO_ROWS
        assert all(len(row) == _HQ_LOGO_W for row in _HQ_PIXEL_GRID)

    def test_pixel_grid_contains_brand_colors(self):
        # Sanity check the decode against the known brand palette (lib.colors.DENDROS_TAG
        # uses the same blue (0,75,107) / orange (224,127,0)) rather than just "some color".
        non_none = [c for row in _HQ_PIXEL_GRID for c in row if c is not None]
        assert non_none, "decoded PNG produced no visible pixels at all"

        def _close(c, target, tol=40):
            return all(abs(c[i] - target[i]) <= tol for i in range(3))

        assert any(_close(c, (0, 75, 107)) for c in non_none), "no brand-blue pixels found"
        assert any(_close(c, (224, 127, 0)) for c in non_none), "no brand-orange pixels found"

    def test_extract_pixel_grid_from_lines_matches_dedicated_hq_grid(self):
        # _extract_full_pixel_grid() is the _LOGO_LINES-specific convenience wrapper;
        # confirm the underlying generalized function produces the same HQ grid directly.
        assert _extract_pixel_grid_from_lines(_HQ_LOGO_LINES, _HQ_LOGO_W) == _HQ_PIXEL_GRID

    def test_build_small_logo_uses_hq_grid_not_low_res_one(self):
        # Downsampling straight from the low-res 42x21-derived grid to the same target
        # size should generally differ from downsampling the 84x84 HQ grid -- if these
        # ever matched exactly it would mean build_small_logo() regressed to the old source.
        from lib.logo import _FULL_PIXEL_GRID
        hq = _downsample_pixel_grid(_HQ_PIXEL_GRID, 12, 12)
        lowres = _downsample_pixel_grid(_FULL_PIXEL_GRID, 12, 12)
        assert hq != lowres


# ── _UNCHANGED sentinel ───────────────────────────────────────────────────────

class TestUnchangedSentinel:
    def test_is_not_none(self):
        assert _UNCHANGED is not None

    def test_is_not_a_string(self):
        assert _UNCHANGED != "null"
        assert _UNCHANGED != ""

    def test_identity_comparison(self):
        assert _UNCHANGED is _UNCHANGED


# ── crash alert config keys ───────────────────────────────────────────────────

class TestCrashAlertConfig:
    def test_defaults_have_crash_alert_on(self):
        assert _DEFAULTS["crash_alert"] is True

    def test_defaults_have_node_color(self):
        assert _DEFAULTS["crash_alert_color"] == "node"

    def test_fields_include_crash_alert(self):
        keys = [f[0] for f in _FIELDS]
        assert "crash_alert" in keys
        assert "crash_alert_color" in keys
        assert "crash_alert_corner" not in keys

    def test_crash_alert_is_cycle_field(self):
        field = next(f for f in _FIELDS if f[0] == "crash_alert")
        assert field[2] == "cycle"
        assert False in field[3] and True in field[3]

    def test_crash_alert_color_options(self):
        field = next(f for f in _FIELDS if f[0] == "crash_alert_color")
        opts = field[3]
        assert "node" in opts
        assert "red" in opts

    def test_descs_have_crash_alert(self):
        assert "crash_alert" in _DESCS
        assert "crash_alert_color" in _DESCS
        assert "crash_alert_corner" not in _DESCS


# ── show_timestamp / show_logger_name config keys ─────────────────────────────

class TestLogMetadataConfig:
    def test_defaults_show_both_by_default(self):
        assert _DEFAULTS["show_timestamp"] is True
        assert _DEFAULTS["show_logger_name"] is True

    def test_fields_include_both_keys(self):
        keys = [f[0] for f in _FIELDS]
        assert "show_timestamp" in keys
        assert "show_logger_name" in keys

    def test_both_are_cycle_fields(self):
        for key in ("show_timestamp", "show_logger_name"):
            field = next(f for f in _FIELDS if f[0] == key)
            assert field[2] == "cycle"
            assert True in field[3] and False in field[3]

    def test_descs_present(self):
        assert "show_timestamp" in _DESCS
        assert "show_logger_name" in _DESCS

    def test_load_crash_alert_true(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"crash_alert": True}, f)
        result = load_global_config()
        assert result["crash_alert"] is True

    def test_load_crash_alert_color_red(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"crash_alert_color": "red"}, f)
        result = load_global_config()
        assert result["crash_alert_color"] == "red"

    def test_defaults_have_interval_30(self):
        assert _DEFAULTS["crash_alert_interval"] == 30

    def test_load_crash_alert_interval(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"crash_alert_interval": 60}, f)
        result = load_global_config()
        assert result["crash_alert_interval"] == 60

    def test_interval_text_field_in_tui(self):
        field = next(f for f in _FIELDS if f[0] == "crash_alert_interval")
        assert field[2] == "text"

    def test_save_and_reload_crash_alert(self, tmp_config):
        cfg = dict(_DEFAULTS)
        cfg["crash_alert"] = True
        cfg["crash_alert_color"] = "red"
        cfg["crash_alert_interval"] = 15
        save_global_config(cfg)
        reloaded = load_global_config()
        assert reloaded["crash_alert"] is True
        assert reloaded["crash_alert_color"] == "red"
        assert reloaded["crash_alert_interval"] == 15


class TestTracebackColorConfig:
    def test_defaults_have_fancy(self):
        assert _DEFAULTS["traceback_color"] == "fancy"

    def test_field_is_cycle(self):
        field = next(f for f in _FIELDS if f[0] == "traceback_color")
        assert field[2] == "cycle"
        assert set(field[3]) == {"fancy", "red", "off"}

    def test_desc_present(self):
        assert "traceback_color" in _DESCS

    def test_load_traceback_color_off(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"traceback_color": "off"}, f)
        result = load_global_config()
        assert result["traceback_color"] == "off"

    def test_load_traceback_color_red(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"traceback_color": "red"}, f)
        result = load_global_config()
        assert result["traceback_color"] == "red"

    def test_roundtrip_traceback_color(self, tmp_config):
        cfg = dict(_DEFAULTS)
        cfg["traceback_color"] = "red"
        save_global_config(cfg)
        assert load_global_config()["traceback_color"] == "red"


# ── tag_style config keys ─────────────────────────────────────────────────────

class TestTagStyleConfig:
    def test_default_is_normal(self):
        assert _DEFAULTS["tag_style"] == "normal"

    def test_field_is_cycle(self):
        field = next(f for f in _FIELDS if f[0] == "tag_style")
        assert field[2] == "cycle"
        assert "normal" in field[3]
        assert "inverted" in field[3]

    def test_desc_present(self):
        assert "tag_style" in _DESCS

    def test_load_tag_style_inverted(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"tag_style": "inverted"}, f)
        result = load_global_config()
        assert result["tag_style"] == "inverted"

    def test_load_tag_style_normal(self, tmp_config):
        with open(tmp_config, "w") as f:
            yaml.dump({"tag_style": "normal"}, f)
        result = load_global_config()
        assert result["tag_style"] == "normal"

    def test_roundtrip_tag_style(self, tmp_config):
        cfg = dict(_DEFAULTS)
        cfg["tag_style"] = "inverted"
        save_global_config(cfg)
        assert load_global_config()["tag_style"] == "inverted"
