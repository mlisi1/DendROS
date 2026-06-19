"""Unit tests for lib/keywords.py — build, resolve, and apply keyword highlights."""

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from lib.keywords import build_keyword_highlights, resolve_node_keywords, apply_keyword_highlights
from lib.colors import _resolve_color, RESET

BLUE = _resolve_color('blue')      # '34'
RED  = _resolve_color('bold red')  # '31;1'
CYAN = _resolve_color('bold cyan') # '36;1'


# ── build_keyword_highlights ──────────────────────────────────────────────────

class TestBuildKeywordHighlights:
    def test_empty_list_returns_empty(self):
        assert build_keyword_highlights([], BLUE) == []

    def test_none_list_returns_empty(self):
        assert build_keyword_highlights(None, BLUE) == []

    def test_entry_missing_word_skipped(self):
        assert build_keyword_highlights([{'color': 'red'}], BLUE) == []

    def test_literal_word_escaped_in_pattern(self):
        results = build_keyword_highlights([{'word': 'a.b'}], BLUE)
        assert len(results) == 1
        pattern, _ = results[0]
        # dot is escaped — only matches literal 'a.b', not 'axb'
        assert pattern.search('a.b') is not None
        assert pattern.search('axb') is None

    def test_no_explicit_color_uses_default_code(self):
        results = build_keyword_highlights([{'word': 'test'}], BLUE)
        _, code = results[0]
        assert code == BLUE

    def test_explicit_color_overrides_default(self):
        results = build_keyword_highlights([{'word': 'test', 'color': 'bold red'}], BLUE)
        _, code = results[0]
        assert code == RED

    def test_bold_flag_appends_1(self):
        results = build_keyword_highlights([{'word': 'test', 'bold': True}], BLUE)
        _, code = results[0]
        assert code == f'{BLUE};1'

    def test_bold_not_duplicated_when_already_bold(self):
        bold_blue = _resolve_color('bold blue')  # already contains '1'
        results = build_keyword_highlights([{'word': 'test', 'bold': True}], bold_blue)
        _, code = results[0]
        assert code.count('1') == 1

    def test_inverted_flag_appends_7(self):
        results = build_keyword_highlights([{'word': 'test', 'inverted': True}], BLUE)
        _, code = results[0]
        assert code.endswith(';7')

    def test_bold_and_inverted_both_applied(self):
        results = build_keyword_highlights([{'word': 'test', 'bold': True, 'inverted': True}], BLUE)
        _, code = results[0]
        parts = code.split(';')
        assert '1' in parts
        assert '7' in parts

    def test_case_insensitive_by_default(self):
        results = build_keyword_highlights([{'word': 'warn'}], BLUE)
        pattern, _ = results[0]
        assert pattern.search('WARN') is not None
        assert pattern.search('Warn') is not None

    def test_case_sensitive_flag(self):
        results = build_keyword_highlights([{'word': 'Warn', 'case_sensitive': True}], BLUE)
        pattern, _ = results[0]
        assert pattern.search('Warn') is not None
        assert pattern.search('WARN') is None

    def test_regex_true_not_escaped(self):
        results = build_keyword_highlights([{'word': r'pos: \d+', 'regex': True, 'color': 'cyan'}], BLUE)
        assert len(results) == 1
        pattern, _ = results[0]
        assert pattern.search('pos: 42') is not None
        assert pattern.search('pos: abc') is None

    def test_regex_false_literal_dot_not_a_wildcard(self):
        results = build_keyword_highlights([{'word': 'a.b', 'regex': False}], BLUE)
        pattern, _ = results[0]
        assert pattern.search('a.b') is not None
        assert pattern.search('axb') is None

    def test_invalid_regex_entry_skipped(self):
        results = build_keyword_highlights([{'word': '[invalid', 'regex': True}], BLUE)
        assert results == []

    def test_multiple_entries_returned_in_order(self):
        entries = [{'word': 'alpha'}, {'word': 'beta'}, {'word': 'gamma'}]
        results = build_keyword_highlights(entries, BLUE)
        patterns = [p.pattern for p, _ in results]
        assert patterns == [re.escape('alpha'), re.escape('beta'), re.escape('gamma')]

    def test_empty_default_code_with_no_color_produces_empty_code(self):
        # Entry with no color and empty default → skipped (no code)
        results = build_keyword_highlights([{'word': 'test'}], '')
        assert results == []

    def test_explicit_color_with_empty_default_still_works(self):
        results = build_keyword_highlights([{'word': 'test', 'color': 'red'}], '')
        assert len(results) == 1


# ── apply_keyword_highlights ──────────────────────────────────────────────────

class TestApplyKeywordHighlights:
    def _highlights(self, word, code=RED):
        return build_keyword_highlights([{'word': word, 'color': 'bold red'}], BLUE)

    def test_no_highlights_returns_unchanged(self):
        line = '[talker-1] hello world\n'
        assert apply_keyword_highlights(line, []) == line

    def test_keyword_in_plain_text_gets_colored(self):
        kws = build_keyword_highlights([{'word': 'error', 'color': 'bold red'}], BLUE)
        result = apply_keyword_highlights('some error here\n', kws)
        assert f'\033[{RED}merror\033[0m' in result

    def test_text_before_and_after_keyword_unchanged(self):
        kws = build_keyword_highlights([{'word': 'error', 'color': 'bold red'}], BLUE)
        result = apply_keyword_highlights('before error after\n', kws)
        assert 'before ' in result
        assert ' after' in result

    def test_keyword_in_colored_segment_restores_color(self):
        # Simulate full_line output: \033[34mtext error text\033[0m
        line = f'\033[{BLUE}mtext error text\033[0m\n'
        kws = build_keyword_highlights([{'word': 'error', 'color': 'bold red'}], BLUE)
        result = apply_keyword_highlights(line, kws)
        # After keyword, should restore to BLUE
        assert f'\033[{RED}merror\033[{BLUE}m' in result

    def test_keyword_in_reset_segment_restores_to_reset(self):
        # After a RESET the active_code is None
        line = f'\033[{BLUE}m[tag]\033[0m rest error here\n'
        kws = build_keyword_highlights([{'word': 'error', 'color': 'bold red'}], BLUE)
        result = apply_keyword_highlights(line, kws)
        # After keyword, restore is RESET (no active color)
        assert f'\033[{RED}merror{RESET}' in result

    def test_multiple_keywords_same_line(self):
        kws = build_keyword_highlights([
            {'word': 'warn', 'color': 'bold yellow'},
            {'word': 'error', 'color': 'bold red'},
        ], BLUE)
        result = apply_keyword_highlights('warn then error\n', kws)
        assert '\033[33;1m' in result  # yellow for warn
        assert f'\033[{RED}m' in result  # red for error

    def test_keyword_case_insensitive_preserves_original_case(self):
        kws = build_keyword_highlights([{'word': 'warn', 'color': 'bold yellow'}], BLUE)
        result = apply_keyword_highlights('this is a WARN message\n', kws)
        assert 'WARN' in result  # original case preserved

    def test_keyword_case_sensitive_not_matched(self):
        kws = build_keyword_highlights([{'word': 'WARN', 'case_sensitive': True, 'color': 'bold yellow'}], BLUE)
        result = apply_keyword_highlights('this is a warn message\n', kws)
        assert '\033[33;1m' not in result

    def test_regex_keyword_matched(self):
        kws = build_keyword_highlights([{'word': r'pos: \d+', 'regex': True, 'color': 'bold cyan'}], BLUE)
        result = apply_keyword_highlights('robot pos: 42 reported\n', kws)
        assert f'\033[{CYAN}m' in result
        assert 'pos: 42' in result

    def test_ansi_codes_in_line_not_matched(self):
        # ANSI code \033[34m contains digits — keyword '34' should NOT match it
        line = f'\033[{BLUE}mhello\033[0m\n'
        kws = build_keyword_highlights([{'word': '34', 'color': 'bold red'}], BLUE)
        result = apply_keyword_highlights(line, kws)
        # The ANSI open and close codes must not be modified
        assert result.startswith(f'\033[{BLUE}m')

    def test_empty_string_no_crash(self):
        kws = build_keyword_highlights([{'word': 'test', 'color': 'red'}], BLUE)
        assert apply_keyword_highlights('', kws) == ''

    def test_keyword_not_in_line_unchanged(self):
        kws = build_keyword_highlights([{'word': 'missing', 'color': 'red'}], BLUE)
        line = 'no match here\n'
        assert apply_keyword_highlights(line, kws) == line

    def test_multiple_occurrences_all_highlighted(self):
        kws = build_keyword_highlights([{'word': 'err', 'color': 'bold red'}], BLUE)
        result = apply_keyword_highlights('err one err two err\n', kws)
        assert result.count(f'\033[{RED}m') == 3

    def test_bold_keyword_uses_node_color_with_bold(self):
        kws = build_keyword_highlights([{'word': 'ok', 'bold': True}], BLUE)
        _, code = kws[0]
        assert code == f'{BLUE};1'
        result = apply_keyword_highlights('status ok now\n', kws)
        assert f'\033[{BLUE};1m' in result

    def test_inverted_keyword(self):
        kws = build_keyword_highlights([{'word': 'alert', 'inverted': True}], BLUE)
        _, code = kws[0]
        assert '7' in code.split(';')
        result = apply_keyword_highlights('alert raised\n', kws)
        assert f'\033[{code}m' in result


# ── resolve_node_keywords (unit) ──────────────────────────────────────────────

class TestResolveNodeKeywordsUnit:
    def _kws(self, word='test'):
        return build_keyword_highlights([{'word': word, 'color': 'red'}], BLUE)

    def test_empty_map_returns_empty(self):
        assert resolve_node_keywords('talker', {}) == []

    def test_exact_full_path(self):
        kws = self._kws()
        assert resolve_node_keywords('/ns/talker', {'/ns/talker': kws}) is kws

    def test_exact_basename(self):
        kws = self._kws()
        assert resolve_node_keywords('/ns/talker', {'talker': kws}) is kws

    def test_exact_full_path_beats_basename(self):
        full_kws = self._kws('full')
        base_kws = self._kws('base')
        result = resolve_node_keywords('/ns/talker', {'/ns/talker': full_kws, 'talker': base_kws})
        assert result is full_kws

    def test_wildcard_full_path(self):
        kws = self._kws()
        assert resolve_node_keywords('/ns/talker', {'*/talker': kws}) is kws

    def test_wildcard_basename(self):
        kws = self._kws()
        assert resolve_node_keywords('nav2_controller', {'nav2_*': kws}) is kws

    def test_no_match_returns_empty_list(self):
        assert resolve_node_keywords('unknown', {'talker': self._kws()}) == []
