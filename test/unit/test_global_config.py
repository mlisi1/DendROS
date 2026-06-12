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
    _UNCHANGED,
    _val_str,
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
            "init_modify_build": False,
            "init_on_existing": "overwrite",
            "init_color": "null",
            "init_color_bold": True,
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
            "init_modify_build": False,
            "init_on_existing": "overwrite",
            "init_color": "null",
            "init_color_bold": True,
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


# ── _UNCHANGED sentinel ───────────────────────────────────────────────────────

class TestUnchangedSentinel:
    def test_is_not_none(self):
        assert _UNCHANGED is not None

    def test_is_not_a_string(self):
        assert _UNCHANGED != "null"
        assert _UNCHANGED != ""

    def test_identity_comparison(self):
        assert _UNCHANGED is _UNCHANGED
