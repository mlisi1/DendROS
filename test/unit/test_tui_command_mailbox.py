"""Tests for the TUI console command mailbox (lib.global_config's
get_tui_command_path/set_tui_command/pop_tui_command) — the cross-process channel behind
`dendros focus <node>` / `dendros clear` reaching an already-running `ros2 launch` TUI
session. Mirrors test_live_disable.py's fixture/style for the sibling disable.flag
mechanism, but this mailbox carries a payload and is one-shot (consumed on read) rather
than a persistent boolean.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

import lib.global_config as gc_mod
from lib.global_config import (
    get_tui_command_path,
    set_tui_command,
    pop_tui_command,
)


@pytest.fixture
def tmp_config(monkeypatch, tmp_path):
    path = str(tmp_path / "defaults.yaml")
    monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", path)
    return path


class TestTuiCommandMailboxHelpers:
    def test_path_lives_alongside_defaults_yaml(self, tmp_config):
        assert os.path.dirname(get_tui_command_path()) == os.path.dirname(tmp_config)
        assert get_tui_command_path().endswith('tui_command.flag')

    def test_pop_returns_none_when_no_file(self, tmp_config):
        assert pop_tui_command() is None

    def test_set_then_pop_roundtrips_payload(self, tmp_config):
        set_tui_command('focus talker')
        assert pop_tui_command() == 'focus talker'

    def test_pop_deletes_file_after_reading(self, tmp_config):
        set_tui_command('clear')
        assert pop_tui_command() == 'clear'
        assert not os.path.isfile(get_tui_command_path())
        assert pop_tui_command() is None  # second pop: nothing left to consume

    def test_set_overwrites_pending_unconsumed_command(self, tmp_config):
        set_tui_command('focus talker')
        set_tui_command('focus listener')  # last-write-wins, no queueing
        assert pop_tui_command() == 'focus listener'
        assert pop_tui_command() is None

    def test_creates_parent_directory(self, monkeypatch, tmp_path):
        deep_path = str(tmp_path / "a" / "b" / "defaults.yaml")
        monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", deep_path)
        set_tui_command('clear')
        assert os.path.isfile(get_tui_command_path())

    def test_pop_is_noop_safe_when_directory_missing(self, monkeypatch, tmp_path):
        deep_path = str(tmp_path / "nonexistent" / "defaults.yaml")
        monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", deep_path)
        assert pop_tui_command() is None  # must not raise
