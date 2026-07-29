"""Tests for the system-wide live-disable mechanism (lib.global_config flag helpers
plus the dendROS_pipe.py passthrough branch that reads them).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

import lib.global_config as gc_mod
from lib.global_config import (
    get_disable_flag_path,
    is_disable_flag_set,
    set_disable_flag,
)

from conftest import run_pipe, assert_segment_colored, assert_segment_uncolored, ANSI_RE

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'configs')


@pytest.fixture
def tmp_config(monkeypatch, tmp_path):
    path = str(tmp_path / "defaults.yaml")
    monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", path)
    return path


def make_prefix(tmp_path, pkg_name, config_yaml_path):
    config_dir = tmp_path / 'share' / pkg_name / 'config'
    config_dir.mkdir(parents=True)
    dest = config_dir / 'dendROS.yaml'
    dest.write_bytes(open(config_yaml_path, 'rb').read())
    return str(tmp_path)


def fixture_config(name):
    return os.path.join(CONFIGS_DIR, name)


# ── flag helpers ──────────────────────────────────────────────────────────────

class TestDisableFlagHelpers:
    def test_path_lives_alongside_defaults_yaml(self, tmp_config):
        assert os.path.dirname(get_disable_flag_path()) == os.path.dirname(tmp_config)
        assert get_disable_flag_path().endswith('disable.flag')

    def test_not_set_when_no_file(self, tmp_config):
        assert not is_disable_flag_set()

    def test_set_disable_flag_true_creates_file(self, tmp_config):
        set_disable_flag(True)
        assert os.path.isfile(get_disable_flag_path())
        assert is_disable_flag_set()

    def test_set_disable_flag_false_removes_file(self, tmp_config):
        set_disable_flag(True)
        set_disable_flag(False)
        assert not os.path.isfile(get_disable_flag_path())
        assert not is_disable_flag_set()

    def test_set_disable_flag_false_is_noop_when_absent(self, tmp_config):
        set_disable_flag(False)  # must not raise
        assert not is_disable_flag_set()

    def test_creates_parent_directory(self, monkeypatch, tmp_path):
        deep_path = str(tmp_path / "a" / "b" / "defaults.yaml")
        monkeypatch.setattr(gc_mod, "GLOBAL_CONFIG_PATH", deep_path)
        set_disable_flag(True)
        assert os.path.isfile(get_disable_flag_path())

    def test_set_true_twice_is_idempotent(self, tmp_config):
        set_disable_flag(True)
        set_disable_flag(True)  # must not raise
        assert is_disable_flag_set()


# ── pipeline passthrough behavior ─────────────────────────────────────────────

class TestPipelinePassthrough:
    PKG = 'test_pkg'

    def test_colorized_when_flag_absent(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert_segment_colored(stdout, '[talker-1]', '34')

    def test_passthrough_when_flag_present(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        flag_dir = tmp_path / '.config' / 'dendROS'
        flag_dir.mkdir(parents=True)
        (flag_dir / 'disable.flag').touch()

        lines = ["[talker-1] [INFO] [1234.5] [/talker]: Hello\n"]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert not ANSI_RE.search(stdout), f"Expected plain passthrough, got: {stdout!r}"
        assert stdout == lines[0]

    def test_passthrough_preserves_line_content_exactly(self, tmp_path):
        prefix = make_prefix(tmp_path, self.PKG, fixture_config('basic.yaml'))
        flag_dir = tmp_path / '.config' / 'dendROS'
        flag_dir.mkdir(parents=True)
        (flag_dir / 'disable.flag').touch()

        lines = [
            "[talker-1] [INFO] [1234.5] [/talker]: Hello\n",
            "[listener-2] [INFO] [1234.6] [/listener]: World\n",
        ]
        stdout, _, _ = run_pipe(prefix, self.PKG, lines)
        assert stdout == ''.join(lines)
