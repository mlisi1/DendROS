"""Tests for _resolve_color and _hex_to_ansi — all color format combinations."""
import pytest
from lib.colors import _resolve_color, _hex_to_ansi


# ── _hex_to_ansi ─────────────────────────────────────────────────────────────

class TestHexToAnsi:
    def test_basic_orange(self):
        assert _hex_to_ansi('FF6600') == '38;2;255;102;0'

    def test_black(self):
        assert _hex_to_ansi('000000') == '38;2;0;0;0'

    def test_white(self):
        assert _hex_to_ansi('FFFFFF') == '38;2;255;255;255'

    def test_pure_red(self):
        assert _hex_to_ansi('FF0000') == '38;2;255;0;0'

    def test_pure_green(self):
        assert _hex_to_ansi('00FF00') == '38;2;0;255;0'

    def test_pure_blue(self):
        assert _hex_to_ansi('0000FF') == '38;2;0;0;255'

    def test_bold_flag_false(self):
        assert _hex_to_ansi('FF6600', bold=False) == '38;2;255;102;0'

    def test_bold_flag_true(self):
        assert _hex_to_ansi('FF6600', bold=True) == '1;38;2;255;102;0'

    def test_mixed_case_hex(self):
        # _hex_to_ansi receives the 6-char string from regex group; case handled upstream
        assert _hex_to_ansi('ff6600') == '38;2;255;102;0'


# ── Raw ANSI passthrough ──────────────────────────────────────────────────────

class TestRawAnsi:
    def test_single_code(self):
        assert _resolve_color('92') == '92'

    def test_compound_code(self):
        assert _resolve_color('34;1') == '34;1'

    def test_reset_code(self):
        assert _resolve_color('0') == '0'

    def test_three_part(self):
        assert _resolve_color('1;31;4') == '1;31;4'

    def test_whitespace_stripped(self):
        assert _resolve_color('  34;1  ') == '34;1'


# ── Named colors (plain) ──────────────────────────────────────────────────────

class TestNamedColorsPlain:
    @pytest.mark.parametrize('name,code', [
        ('black',   '30'),
        ('red',     '31'),
        ('green',   '32'),
        ('yellow',  '33'),
        ('blue',    '34'),
        ('magenta', '35'),
        ('cyan',    '36'),
        ('white',   '37'),
    ])
    def test_all_named_colors(self, name, code):
        assert _resolve_color(name) == code

    def test_uppercase_input(self):
        assert _resolve_color('BLUE') == '34'

    def test_mixed_case_input(self):
        assert _resolve_color('Blue') == '34'


# ── Named colors + bold ───────────────────────────────────────────────────────

class TestBoldModifier:
    @pytest.mark.parametrize('name,expected', [
        ('bold black',   '30;1'),
        ('bold red',     '31;1'),
        ('bold green',   '32;1'),
        ('bold yellow',  '33;1'),
        ('bold blue',    '34;1'),
        ('bold magenta', '35;1'),
        ('bold cyan',    '36;1'),
        ('bold white',   '37;1'),
    ])
    def test_bold_all_colors(self, name, expected):
        assert _resolve_color(name) == expected


# ── Named colors + light/bright ───────────────────────────────────────────────

class TestLightBrightModifier:
    @pytest.mark.parametrize('name,expected', [
        ('light black',   '90'),
        ('light red',     '91'),
        ('light green',   '92'),
        ('light yellow',  '93'),
        ('light blue',    '94'),
        ('light magenta', '95'),
        ('light cyan',    '96'),
        ('light white',   '97'),
    ])
    def test_light_all_colors(self, name, expected):
        assert _resolve_color(name) == expected

    @pytest.mark.parametrize('name,expected', [
        ('bright black',   '90'),
        ('bright red',     '91'),
        ('bright green',   '92'),
        ('bright yellow',  '93'),
        ('bright blue',    '94'),
        ('bright magenta', '95'),
        ('bright cyan',    '96'),
        ('bright white',   '97'),
    ])
    def test_bright_alias(self, name, expected):
        assert _resolve_color(name) == expected


# ── Named colors + dark/dim ───────────────────────────────────────────────────

class TestDarkDimModifier:
    @pytest.mark.parametrize('name,expected', [
        ('dark black',   '30;2'),
        ('dark red',     '31;2'),
        ('dark green',   '32;2'),
        ('dark yellow',  '33;2'),
        ('dark blue',    '34;2'),
        ('dark magenta', '35;2'),
        ('dark cyan',    '36;2'),
        ('dark white',   '37;2'),
    ])
    def test_dark_all_colors(self, name, expected):
        assert _resolve_color(name) == expected

    @pytest.mark.parametrize('name,expected', [
        ('dim red',   '31;2'),
        ('dim blue',  '34;2'),
        ('dim green', '32;2'),
    ])
    def test_dim_alias(self, name, expected):
        assert _resolve_color(name) == expected


# ── Combined modifiers ────────────────────────────────────────────────────────

class TestCombinedModifiers:
    def test_bold_light_cyan(self):
        assert _resolve_color('bold light cyan') == '96;1'

    def test_bold_bright_red(self):
        assert _resolve_color('bold bright red') == '91;1'

    def test_light_bold_blue(self):
        # word order should not matter
        assert _resolve_color('light bold blue') == '94;1'

    def test_bold_light_magenta(self):
        assert _resolve_color('bold light magenta') == '95;1'

    def test_bold_bright_white(self):
        assert _resolve_color('bold bright white') == '97;1'


# ── Hex truecolor ─────────────────────────────────────────────────────────────

class TestHexColors:
    def test_hash_normal(self):
        assert _resolve_color('#FF6600') == '38;2;255;102;0'

    def test_hash_lowercase(self):
        assert _resolve_color('#ff6600') == '38;2;255;102;0'

    def test_hash_mixed_case(self):
        assert _resolve_color('#Ff6600') == '38;2;255;102;0'

    def test_hash_black(self):
        assert _resolve_color('#000000') == '38;2;0;0;0'

    def test_hash_white(self):
        assert _resolve_color('#FFFFFF') == '38;2;255;255;255'

    def test_at_bold(self):
        assert _resolve_color('@#FF6600') == '1;38;2;255;102;0'

    def test_at_bold_lowercase(self):
        assert _resolve_color('@#ff6600') == '1;38;2;255;102;0'

    def test_bold_word_hex(self):
        assert _resolve_color('bold #FF6600') == '1;38;2;255;102;0'

    def test_bold_word_hex_lowercase(self):
        assert _resolve_color('bold #ff6600') == '1;38;2;255;102;0'

    def test_at_vs_bold_word_equivalent(self):
        assert _resolve_color('@#00AAFF') == _resolve_color('bold #00AAFF')

    def test_dark_modifier_ignored_for_hex(self):
        # dark/light do not apply to hex — user controls the RGB
        # 'dark #FF6600' has no named color word, so falls through to hex path
        assert _resolve_color('dark #FF6600') == '38;2;255;102;0'

    def test_light_modifier_ignored_for_hex(self):
        assert _resolve_color('light #FF6600') == '38;2;255;102;0'

    def test_custom_color_00AAFF(self):
        assert _resolve_color('#00AAFF') == '38;2;0;170;255'

    def test_custom_color_00FF44(self):
        assert _resolve_color('#00FF44') == '38;2;0;255;68'


# ── Unknown / edge cases ──────────────────────────────────────────────────────

class TestEdgeCases:
    def test_unknown_returns_as_is(self):
        assert _resolve_color('bue') == 'bue'

    def test_empty_string(self):
        assert _resolve_color('') == ''

    def test_whitespace_only(self):
        # Empty after strip → empty string returned as-is
        assert _resolve_color('   ') == ''

    def test_leading_trailing_whitespace_named(self):
        assert _resolve_color('  blue  ') == '34'

    def test_leading_trailing_whitespace_raw(self):
        assert _resolve_color('  34;1  ') == '34;1'

    def test_numeric_string_not_color(self):
        # Purely numeric → treated as raw ANSI code, passed through
        assert _resolve_color('99') == '99'

    def test_integer_input_coerced(self):
        # _resolve_color does str(value) first
        assert _resolve_color(34) == '34'
