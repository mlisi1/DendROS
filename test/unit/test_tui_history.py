"""Tests for lib/tui_history.py — per-terminal persistence of the TUI's last run, behind
`dendros reopen`. Mirrors test_tui_command_mailbox.py's tmp_config fixture."""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

import lib.global_config as gc_mod
from lib.tui_history import (
    current_shell_id,
    get_history_dir,
    get_history_path,
    load_last_run,
    prune_stale,
    save_last_run,
)
from lib.tui_pure import RingLog, segments_from_ansi


@pytest.fixture
def tmp_config(monkeypatch, tmp_path):
    path = str(tmp_path / "defaults.yaml")
    monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", path)
    return path


def _entry(ansi, node=None, logger=None):
    segments = segments_from_ansi(ansi)
    return (segments, ''.join(s[0] for s in segments), node, logger)


def _dead_pid():
    proc = subprocess.Popen([sys.executable, '-c', 'pass'])
    proc.wait()
    return proc.pid


class TestShellId:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv('DENDROS_SHELL_PID', '4242')
        assert current_shell_id() == 4242

    def test_falls_back_to_parent_pid(self, monkeypatch):
        monkeypatch.delenv('DENDROS_SHELL_PID', raising=False)
        assert current_shell_id() == os.getppid()

    def test_garbage_env_falls_back(self, monkeypatch):
        monkeypatch.setenv('DENDROS_SHELL_PID', 'abc')
        assert current_shell_id() == os.getppid()


class TestPaths:
    def test_dir_lives_alongside_defaults_yaml(self, tmp_config):
        assert os.path.dirname(get_history_dir()) == os.path.dirname(tmp_config)

    def test_one_file_per_shell(self, tmp_config):
        assert get_history_path(11) != get_history_path(12)
        assert get_history_path(11).endswith('11.jsonl')


class TestSaveLoad:
    def test_load_missing_returns_none(self, tmp_config):
        assert load_last_run(shell_id=os.getpid()) is None

    def test_roundtrip_preserves_entries_exactly(self, tmp_config):
        entries = [
            _entry('\033[34;1m[talker-1]\033[0m [INFO] hello', 'talker', 'talker'),
            _entry('plain line'),
            _entry('\033[38;2;255;102;0m[comp]\033[0m x', 'container', 'lidar_driver'),
        ]
        save_last_run(entries, ['launch', 'pkg', 'a.launch.py'], 'BANNER', shell_id=os.getpid())
        run = load_last_run(shell_id=os.getpid())
        assert run['entries'] == entries
        assert run['argv'] == ['launch', 'pkg', 'a.launch.py']
        assert run['banner'] == 'BANNER'
        assert isinstance(run['saved_at'], float)

    def test_loaded_entries_feed_a_ringlog(self, tmp_config):
        ring = RingLog(maxlen=10)
        for e in [_entry('\033[31ma\033[0m', 'n1', 'l1'), _entry('b')]:
            ring.append(*e)
        save_last_run(ring.entries(), shell_id=os.getpid())
        restored = RingLog(maxlen=10)
        for e in load_last_run(shell_id=os.getpid())['entries']:
            restored.append(*e)
        assert restored.entries() == ring.entries()
        assert restored.node_identities() == [('n1', 'l1'), (None, None)]

    def test_save_overwrites_previous_run(self, tmp_config):
        save_last_run([_entry('old')], shell_id=os.getpid())
        save_last_run([_entry('new')], shell_id=os.getpid())
        assert [e[1] for e in load_last_run(shell_id=os.getpid())['entries']] == ['new']

    def test_terminals_are_independent(self, tmp_config):
        me, parent = os.getpid(), os.getppid()
        save_last_run([_entry('mine')], shell_id=me)
        save_last_run([_entry('theirs')], shell_id=parent)
        assert load_last_run(shell_id=me)['entries'][0][1] == 'mine'
        assert load_last_run(shell_id=parent)['entries'][0][1] == 'theirs'

    def test_no_tmp_files_left_behind(self, tmp_config):
        save_last_run([_entry('x')], shell_id=os.getpid())
        assert os.listdir(get_history_dir()) == [f'{os.getpid()}.jsonl']

    def test_corrupt_file_returns_none(self, tmp_config):
        os.makedirs(get_history_dir(), exist_ok=True)
        with open(get_history_path(os.getpid()), 'w') as f:
            f.write('not json\n')
        assert load_last_run(shell_id=os.getpid()) is None

    def test_unknown_version_returns_none(self, tmp_config):
        os.makedirs(get_history_dir(), exist_ok=True)
        with open(get_history_path(os.getpid()), 'w') as f:
            f.write(json.dumps({'version': 999}) + '\n')
        assert load_last_run(shell_id=os.getpid()) is None


class TestPrune:
    def test_save_prunes_runs_of_closed_shells(self, tmp_config):
        dead = _dead_pid()
        save_last_run([_entry('stale')], shell_id=dead)
        save_last_run([_entry('live')], shell_id=os.getpid())
        assert not os.path.exists(get_history_path(dead))
        assert os.path.exists(get_history_path(os.getpid()))

    def test_prune_keeps_live_shells_and_ignores_foreign_files(self, tmp_config):
        os.makedirs(get_history_dir(), exist_ok=True)
        live = get_history_path(os.getppid())
        foreign = os.path.join(get_history_dir(), 'notes.txt')
        for p in (live, foreign):
            open(p, 'w').close()
        prune_stale()
        assert os.path.exists(live) and os.path.exists(foreign)

    def test_prune_missing_dir_is_noop(self, tmp_config):
        prune_stale()  # must not raise
