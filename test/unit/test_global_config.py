"""Tests for dendros_config — data-layer helpers only (no curses)."""

import os
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

import dendros_config as cfg_mod
from dendros_config import (
    _DEFAULTS,
    _FIELDS,
    _DESCS,
    _LOGO_LINES,
    _LOGO_W,
    _LOGO_ROWS,
    _LOGO_PARSED,
    _UNCHANGED,
    _val_str,
    _shift_rgb,
    _render_logo_line,
    _make_title_line,
    load_global_config,
    save_global_config,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_config(monkeypatch, tmp_path):
    """Redirect GLOBAL_CONFIG_PATH to a temp file for every test."""
    path = str(tmp_path / "defaults.yaml")
    monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", path)
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
            "show_group_tag": False,
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
        assert result["show_group_tag"] == _DEFAULTS["show_group_tag"]
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
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", deep_path)
        save_global_config(dict(_DEFAULTS))
        assert os.path.exists(deep_path)

    def test_roundtrip_all_defaults(self, tmp_config):
        save_global_config(dict(_DEFAULTS))
        result = load_global_config()
        assert result == _DEFAULTS

    def test_roundtrip_custom_values(self, tmp_config):
        custom = {
            "color_mode": "full_line",
            "show_group_tag": False,
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
        for key, label, kind, opts in _FIELDS:
            if kind == "cycle":
                assert opts is not None and len(opts) >= 2, (
                    f"Cycle field '{key}' needs at least 2 options"
                )

    def test_all_fields_have_descriptions(self):
        for key, _, _, _ in _FIELDS:
            assert key in _DESCS, f"No description for field '{key}'"
            assert len(_DESCS[key]) >= 1

    def test_cycle_options_include_default_value(self):
        """Every default value must appear as a cycle option for its field."""
        for key, _, kind, opts in _FIELDS:
            if kind != "cycle":
                continue
            default = _DEFAULTS[key]
            opt_strs = [str(o) for o in opts]
            assert str(default) in opt_strs, (
                f"Default '{default}' for '{key}' not in cycle options {opts}"
            )


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
    def test_defaults_have_crash_alert_off(self):
        assert _DEFAULTS["crash_alert"] is False

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
