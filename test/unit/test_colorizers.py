"""Tests for colorize_tag_only, colorize_full_line, colorize_line, colorize_launch_msg.

Each test verifies exactly which text segments are colored and which are not.
"""
import re
import pytest
from dendROS_pipe import (
    colorize_tag_only,
    colorize_full_line,
    colorize_line,
    colorize_launch_msg,
    RESET,
)
from conftest import (
    colored_segments,
    assert_segment_colored,
    assert_segment_uncolored,
    assert_no_ansi_after,
    strip_ansi,
    ANSI_RE,
)

# ── Shared test data ──────────────────────────────────────────────────────────

NODE_LINE     = "[talker-1] [INFO] [1234.567890] [/talker]: Publishing: 'Hello World'\n"
NODE_LINE_2   = "[talker-2] [INFO] [1234.600000] [/talker]: Publishing: 'Hello World: 2'\n"
WARN_LINE     = "[talker-1] [WARN] [1234.580000] [/talker]: Something went wrong\n"
LAUNCH_LINE   = "[INFO] [talker-1]: process started with pid [12345]\n"
LAUNCH_WARN   = "[WARN] [talker-1]: process had stderr output: warning\n"
LAUNCH_ERROR  = "[ERROR] [listener-1]: process has died [pid 9999, exit code -11]\n"
PLAIN_LINE    = "Some plain text with no bracket prefix\n"
ANSI_EMBED    = "[talker-1] \033[33m[WARN]\033[0m embedded warning\n"

CODE_BLUE = '34'
CODE_RED  = '31'
LABEL     = 'TALK'


# ── colorize_tag_only ─────────────────────────────────────────────────────────

class TestColorizeTagOnly:
    def test_prefix_colored_exact(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_colored(result, '[talker-1]', CODE_BLUE)

    def test_prefix_is_only_colored_segment(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        segs = colored_segments(result)
        colored = [(t, c) for t, c in segs if c is not None]
        assert len(colored) == 1
        assert colored[0] == ('[talker-1]', CODE_BLUE)

    def test_message_text_uncolored(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_uncolored(result, "Publishing: 'Hello World'")

    def test_log_level_bracket_uncolored(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_uncolored(result, '[INFO]')

    def test_timestamp_uncolored(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_uncolored(result, '[1234.567890]')

    def test_no_ansi_after_prefix_reset(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        # After the reset that closes [talker-1], no more ANSI
        assert_no_ansi_after(result, '[talker-1]' + RESET)

    def test_badge_inserted_when_show_tag_true(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True)
        assert '[TALK]' in result

    def test_badge_colored_same_as_prefix(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True)
        assert_segment_colored(result, ' [TALK]', CODE_BLUE)

    def test_badge_absent_when_show_tag_false(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        assert '[TALK]' not in result

    def test_badge_absent_when_no_label(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, None, show_tag=True)
        assert '[' not in result.split('\033[0m', 1)[-1].split('[', 1)[0]
        # More precisely: TALK never appears
        assert 'TALK' not in result

    def test_message_uncolored_after_badge(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True)
        segs = colored_segments(result)
        # All uncolored text after the badge
        uncolored_texts = [t for t, c in segs if c is None]
        full_uncolored = ''.join(uncolored_texts)
        assert "Publishing: 'Hello World'" in full_uncolored

    def test_badge_comes_before_message(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True)
        badge_pos = result.find('[TALK]')
        msg_pos   = result.find("Publishing:")
        assert badge_pos < msg_pos

    def test_node_numeric_suffix_stripped(self):
        # [talker-2] should colorize identically to [talker-1]
        result = colorize_tag_only(NODE_LINE_2, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_colored(result, '[talker-2]', CODE_BLUE)

    def test_non_matching_line_returned_unchanged(self):
        result = colorize_tag_only(PLAIN_LINE, CODE_BLUE, LABEL, show_tag=True)
        assert result == PLAIN_LINE

    def test_preserves_newline(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        assert result.endswith('\n')

    def test_plain_text_no_ansi_added(self):
        result = colorize_tag_only(PLAIN_LINE, CODE_BLUE, LABEL, show_tag=True)
        assert not ANSI_RE.search(result)

    def test_warn_line_severity_preserved_in_rest(self):
        # WARN severity text must survive unchanged in the uncolored rest
        result = colorize_tag_only(WARN_LINE, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_uncolored(result, '[WARN]')

    def test_exact_structure_no_badge(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False)
        expected_start = f'\033[{CODE_BLUE}m[talker-1]\033[0m'
        assert result.startswith(expected_start)
        # Rest should be exactly the original line minus the prefix
        rest = result[len(expected_start):]
        assert rest == " [INFO] [1234.567890] [/talker]: Publishing: 'Hello World'\n"

    def test_exact_structure_with_badge(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True)
        expected_start = f'\033[{CODE_BLUE}m[talker-1]\033[0m\033[{CODE_BLUE}m [TALK]\033[0m'
        assert result.startswith(expected_start)
        rest = result[len(expected_start):]
        assert rest == " [INFO] [1234.567890] [/talker]: Publishing: 'Hello World'\n"


# ── colorize_full_line ────────────────────────────────────────────────────────

class TestColorizeFullLine:
    def test_output_starts_with_escape(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE)
        assert result.startswith(f'\033[{CODE_BLUE}m')

    def test_output_ends_with_reset_newline(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE)
        assert result.endswith(RESET + '\n')

    def test_only_one_active_color_code(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE)
        segs = colored_segments(result)
        active_codes = {c for _, c in segs if c is not None}
        assert active_codes == {CODE_BLUE}

    def test_plain_text_matches_after_strip(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE)
        assert strip_ansi(result).rstrip('\n') == strip_ansi(NODE_LINE).rstrip('\n')

    def test_inner_ansi_stripped(self):
        # Input has embedded \033[33m...\033[0m — must not appear in output
        result = colorize_full_line(ANSI_EMBED, CODE_BLUE)
        codes = ANSI_RE.findall(result)
        # Only our outer code and its reset should remain
        assert '33' not in codes

    def test_inner_ansi_stripped_only_outer_remains(self):
        result = colorize_full_line(ANSI_EMBED, CODE_BLUE)
        codes = [c for c in ANSI_RE.findall(result) if c not in ('0', '')]
        assert codes == [CODE_BLUE]

    def test_badge_inserted_after_prefix(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE, label=LABEL, show_tag=True)
        assert '[TALK]' in result
        # Badge must come right after the prefix bracket
        idx_prefix = result.find('[talker-1]')
        idx_badge  = result.find('[TALK]')
        assert idx_prefix < idx_badge

    def test_badge_position_before_rest_of_line(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE, label=LABEL, show_tag=True)
        idx_badge = result.find('[TALK]')
        idx_info  = result.find('[INFO]')
        assert idx_badge < idx_info

    def test_no_badge_when_show_tag_false(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE, label=LABEL, show_tag=False)
        assert '[TALK]' not in result

    def test_entire_content_is_colored(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE)
        segs = colored_segments(result)
        uncolored = [t for t, c in segs if c is None and t.strip()]
        assert not uncolored, f"Unexpected uncolored text: {uncolored}"

    def test_preserves_newline(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE)
        assert result.endswith('\n')

    def test_non_matching_line_still_colored(self):
        # Full-line mode colors even lines without a [node] prefix
        result = colorize_full_line(PLAIN_LINE, CODE_BLUE)
        assert result.startswith(f'\033[{CODE_BLUE}m')
        assert result.endswith(RESET + '\n')


# ── colorize_line dispatch ────────────────────────────────────────────────────

class TestColorizeLineDispatch:
    def test_tag_only_mode(self):
        result_dispatch = colorize_line(NODE_LINE, CODE_BLUE, LABEL, True, 'tag_only')
        result_direct   = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, True)
        assert result_dispatch == result_direct

    def test_full_line_mode(self):
        result_dispatch = colorize_line(NODE_LINE, CODE_BLUE, LABEL, True, 'full_line')
        result_direct   = colorize_full_line(NODE_LINE, CODE_BLUE, LABEL, True)
        assert result_dispatch == result_direct

    def test_unknown_mode_falls_back_to_tag_only(self):
        # Any unrecognized mode should behave like tag_only
        result = colorize_line(NODE_LINE, CODE_BLUE, LABEL, True, 'unknown_mode')
        result_tag_only = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, True)
        assert result == result_tag_only


# ── colorize_launch_msg ───────────────────────────────────────────────────────

class TestColorizeLaunchMsg:
    def test_tag_only_colors_node_bracket_exact(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'tag_only')
        assert_segment_colored(result, '[talker-1]', CODE_BLUE)

    def test_tag_only_level_prefix_uncolored(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'tag_only')
        assert result.startswith('[INFO] ')
        # The [INFO] part has no ANSI code before it
        assert_segment_uncolored(result, '[INFO]')

    def test_tag_only_message_after_bracket_uncolored(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'tag_only')
        assert_segment_uncolored(result, ': process started with pid [12345]')

    def test_tag_only_exact_structure(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'tag_only')
        expected = f'[INFO] \033[{CODE_BLUE}m[talker-1]\033[0m: process started with pid [12345]\n'
        assert result == expected

    def test_tag_only_warn_level_preserved(self):
        result = colorize_launch_msg(LAUNCH_WARN, CODE_BLUE, 'tag_only')
        assert result.startswith('[WARN] ')
        assert_segment_uncolored(result, '[WARN]')
        assert_segment_colored(result, '[talker-1]', CODE_BLUE)

    def test_tag_only_error_level_preserved(self):
        result = colorize_launch_msg(LAUNCH_ERROR, CODE_RED, 'tag_only')
        assert result.startswith('[ERROR] ')
        assert_segment_uncolored(result, '[ERROR]')
        assert_segment_colored(result, '[listener-1]', CODE_RED)

    def test_tag_only_only_node_bracket_colored(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'tag_only')
        segs = colored_segments(result)
        colored = [(t, c) for t, c in segs if c is not None]
        assert len(colored) == 1
        assert colored[0] == ('[talker-1]', CODE_BLUE)

    def test_full_line_mode_entire_line_colored(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'full_line')
        assert result.startswith(f'\033[{CODE_BLUE}m')
        assert result.endswith(RESET + '\n')
        segs = colored_segments(result)
        uncolored = [t for t, c in segs if c is None and t.strip()]
        assert not uncolored

    def test_full_line_plain_text_preserved(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'full_line')
        assert 'process started with pid [12345]' in strip_ansi(result)

    def test_non_matching_line_returned_unchanged(self):
        result = colorize_launch_msg(PLAIN_LINE, CODE_BLUE, 'tag_only')
        assert result == PLAIN_LINE

    def test_node_output_format_not_matched(self):
        # A [node-N] [INFO] ... line is NOT a launch-framework line; should pass through
        result = colorize_launch_msg(NODE_LINE, CODE_BLUE, 'tag_only')
        assert result == NODE_LINE

    def test_preserves_newline_tag_only(self):
        result = colorize_launch_msg(LAUNCH_LINE, CODE_BLUE, 'tag_only')
        assert result.endswith('\n')


# ── WARN/ERROR embedded ANSI preservation ────────────────────────────────────

class TestWarnErrorColors:
    """Verify that ROS severity ANSI codes survive in tag_only mode and are stripped in full_line."""

    # ROS 2 embeds e.g. \033[33m before [WARN] and \033[0m after — these live in
    # the "rest" of the line, which tag_only never touches.
    WARN_ANSI  = "[talker-1] \033[33m[WARN]\033[0m [1234.5] [/t]: Something slow\n"
    ERROR_ANSI = "[talker-1] \033[31m[ERROR]\033[0m [1234.5] [/t]: Fatal issue\n"

    def test_tag_only_warn_ansi_preserved(self):
        result = colorize_tag_only(self.WARN_ANSI, CODE_BLUE, LABEL, show_tag=False)
        # The yellow WARN code from ROS must still be in the output
        assert '\033[33m' in result

    def test_tag_only_error_ansi_preserved(self):
        result = colorize_tag_only(self.ERROR_ANSI, CODE_BLUE, LABEL, show_tag=False)
        assert '\033[31m' in result

    def test_tag_only_warn_prefix_still_colored(self):
        result = colorize_tag_only(self.WARN_ANSI, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_colored(result, '[talker-1]', CODE_BLUE)

    def test_tag_only_error_prefix_still_colored(self):
        result = colorize_tag_only(self.ERROR_ANSI, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_colored(result, '[talker-1]', CODE_BLUE)

    def test_tag_only_message_uncolored(self):
        result = colorize_tag_only(self.WARN_ANSI, CODE_BLUE, LABEL, show_tag=False)
        assert_segment_uncolored(result, 'Something slow')

    def test_full_line_warn_ansi_stripped(self):
        result = colorize_full_line(self.WARN_ANSI, CODE_BLUE)
        codes = ANSI_RE.findall(result)
        assert '33' not in codes

    def test_full_line_error_ansi_stripped(self):
        result = colorize_full_line(self.ERROR_ANSI, CODE_BLUE)
        codes = ANSI_RE.findall(result)
        assert '31' not in codes

    def test_full_line_only_node_code_remains(self):
        result = colorize_full_line(self.WARN_ANSI, CODE_BLUE)
        active = [c for c in ANSI_RE.findall(result) if c not in ('0', '')]
        assert active == [CODE_BLUE]

    def test_full_line_warn_text_preserved(self):
        result = colorize_full_line(self.WARN_ANSI, CODE_BLUE)
        assert 'Something slow' in strip_ansi(result)

    def test_full_line_error_text_preserved(self):
        result = colorize_full_line(self.ERROR_ANSI, CODE_BLUE)
        assert 'Fatal issue' in strip_ansi(result)


# ── tag_position ──────────────────────────────────────────────────────────────

class TestTagPosition:
    """tag_position='before' places the badge before [node-N]; 'after' is the default."""

    def test_tag_only_after_is_default(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True)
        prefix_pos = result.find('[talker-1]')
        badge_pos  = result.find('[TALK]')
        assert prefix_pos < badge_pos

    def test_tag_only_before_places_badge_first(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True, tag_position='before')
        prefix_pos = result.find('[talker-1]')
        badge_pos  = result.find('[TALK]')
        assert badge_pos < prefix_pos

    def test_tag_only_before_exact_structure(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True, tag_position='before')
        expected = (f'\033[{CODE_BLUE}m[TALK]\033[0m'
                    f' \033[{CODE_BLUE}m[talker-1]\033[0m')
        assert result.startswith(expected)

    def test_tag_only_before_badge_colored(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True, tag_position='before')
        assert_segment_colored(result, '[TALK]', CODE_BLUE)

    def test_tag_only_before_prefix_colored(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True, tag_position='before')
        assert_segment_colored(result, '[talker-1]', CODE_BLUE)

    def test_tag_only_before_message_uncolored(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=True, tag_position='before')
        assert_segment_uncolored(result, "Publishing: 'Hello World'")

    def test_tag_only_before_no_tag_when_show_tag_false(self):
        result = colorize_tag_only(NODE_LINE, CODE_BLUE, LABEL, show_tag=False, tag_position='before')
        assert '[TALK]' not in result

    def test_full_line_after_is_default(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE, label=LABEL, show_tag=True)
        plain = strip_ansi(result)
        prefix_pos = plain.find('[talker-1]')
        badge_pos  = plain.find('[TALK]')
        assert prefix_pos < badge_pos

    def test_full_line_before_places_badge_first(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE, label=LABEL, show_tag=True,
                                    tag_position='before')
        plain = strip_ansi(result)
        prefix_pos = plain.find('[talker-1]')
        badge_pos  = plain.find('[TALK]')
        assert badge_pos < prefix_pos

    def test_full_line_before_entirely_colored(self):
        result = colorize_full_line(NODE_LINE, CODE_BLUE, label=LABEL, show_tag=True,
                                    tag_position='before')
        assert result.startswith(f'\033[{CODE_BLUE}m')
        assert result.endswith(RESET + '\n')
