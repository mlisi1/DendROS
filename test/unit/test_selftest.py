"""`dendros test`: lib/selftest.py checks and lib/color_charts.py charts (the curses probe in
dendros_selftest.py is manual-testing only, like the rest of the curses layer)."""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from conftest import REPO_ROOT, assert_segment_colored, strip_ansi

from lib import color_charts as charts
from lib import selftest as st
from lib.colors import _resolve_color, set_ignore_bold
from lib.tui_pure import quantize_rgb_to_256


def _missing(name):
    raise ImportError(name)


class TestDependencyChecks:
    def test_python_ok(self):
        assert st.check_python((3, 10, 2)) == st.Check(st.OK, 'Python', '3.10.2')

    def test_python_too_old(self):
        assert st.check_python((3, 6, 9)).status == st.FAIL

    def test_required_module_missing_fails(self):
        c = st.check_module('PyYAML', 'yaml', True, 'pip3 install pyyaml', importer=_missing)
        assert c.status == st.FAIL and 'pip3 install pyyaml' in c.detail

    def test_optional_module_missing_warns(self):
        assert st.check_module('x', 'x', False, 'hint', importer=_missing).status == st.WARN

    def test_module_version_shown(self):
        c = st.check_module('PyYAML', 'yaml', True, '',
                            importer=lambda n: SimpleNamespace(__version__='6.0'))
        assert c == st.Check(st.OK, 'PyYAML', '6.0')

    def test_curses_missing_warns_about_classic_fallback(self):
        c = st.check_curses(importer=_missing)
        assert c.status == st.WARN and 'classic' in c.detail

    def test_ros2_from_wrapper_env(self):
        c = st.check_ros2(env={'DENDROS_ROS2_BIN': '/x/ros2', 'ROS_DISTRO': 'jazzy'},
                          which=lambda n: None)
        assert c.status == st.OK and '/x/ros2' in c.detail and 'jazzy' in c.detail

    def test_ros2_on_path(self):
        c = st.check_ros2(env={}, which=lambda n: '/opt/ros/jazzy/bin/ros2')
        assert c.status == st.OK and 'ROS_DISTRO=unset' in c.detail

    def test_ros2_missing_fails(self):
        assert st.check_ros2(env={}, which=lambda n: None).status == st.FAIL

    def test_rclpy(self):
        ok = lambda *a, **k: SimpleNamespace(returncode=0)
        bad = lambda *a, **k: SimpleNamespace(returncode=1)

        def hang(*a, **k):
            raise subprocess.TimeoutExpired('python3', 10)
        assert st.check_rclpy(run=ok).status == st.OK
        assert st.check_rclpy(run=bad).status == st.WARN
        assert st.check_rclpy(run=hang).status == st.WARN

    def test_clipboard(self):
        assert st.check_clipboard(which=lambda n: n == 'xsel').detail.startswith('xsel')
        assert st.check_clipboard(which=lambda n: None).status == st.WARN


class TestShellChecks:
    def test_wrapper_not_checked_outside_dendros(self):
        assert st.check_wrapper(env={}).status == st.INFO

    def test_wrapper_function_ok(self):
        assert st.check_wrapper(env={'DENDROS_ROS2_TYPE': 'function'}).status == st.OK

    @pytest.mark.parametrize('kind', ['alias', 'file', ''])
    def test_wrapper_shadowed_fails(self, kind):
        assert st.check_wrapper(env={'DENDROS_ROS2_TYPE': kind}).status == st.FAIL

    def test_enabled(self):
        assert st.check_enabled(env={}, flag_set=False).status == st.OK
        assert st.check_enabled(env={'DENDROS_DISABLE': '0'}, flag_set=False).status == st.OK

    def test_disabled_locally(self):
        c = st.check_enabled(env={'DENDROS_DISABLE': '1'}, flag_set=False)
        assert c.status == st.WARN and 'this shell' in c.detail

    def test_disabled_system_wide(self):
        c = st.check_enabled(env={}, flag_set=True)
        assert c.status == st.WARN and 'system-wide' in c.detail

    def test_config_dir_existing_writable(self, tmp_path):
        assert st.check_config_dir(str(tmp_path)).status == st.OK

    def test_config_dir_created_later(self, tmp_path):
        c = st.check_config_dir(str(tmp_path / 'a' / 'dendROS'))
        assert c.status == st.OK and 'created on first launch' in c.detail

    def test_launch_mode(self):
        assert st.check_launch_mode({'launch_mode': 'classic'}, True).detail == 'classic'
        assert st.check_launch_mode({'launch_mode': 'tui'}, True).detail == 'tui'
        assert 'fall back' in st.check_launch_mode({'launch_mode': 'tui'}, False).detail


class TestValidateGlobalConfig:
    def test_stock_defaults_are_valid(self):
        from lib.global_config import DEFAULTS
        assert st.validate_global_config(dict(DEFAULTS)) == []

    def test_unknown_key(self):
        assert st.validate_global_config({'tag_positon': 'after'}) == ["unknown key 'tag_positon'"]

    def test_bad_choice_lists_options(self):
        (p,) = st.validate_global_config({'tag_position': 'left'})
        assert 'tag_position' in p and 'before' in p and 'after' in p

    def test_bool_choice(self):
        assert st.validate_global_config({'debug': True}) == []
        (p,) = st.validate_global_config({'debug': 'yes'})
        assert 'true|false' in p or 'false|true' in p

    def test_numbers_saved_as_strings_are_valid(self):
        # dendros config's text editor saves '30', the code converts with float()/int().
        assert st.validate_global_config({'crash_alert_interval': '30',
                                          'tui_scrollback_lines': '5000'}) == []
        assert st.validate_global_config({'crash_alert_interval': 2.5}) == []

    @pytest.mark.parametrize('key,value', [
        ('crash_alert_interval', 'soon'), ('crash_alert_interval', -1),
        ('tui_scrollback_lines', 0), ('tui_scrollback_lines', '1.5'),
        ('tui_scrollback_lines', True),
    ])
    def test_bad_numbers(self, key, value):
        assert len(st.validate_global_config({key: value})) == 1

    def test_colors(self):
        assert st.validate_global_config({'unmatched_color': 'bold light cyan'}) == []
        assert st.validate_global_config({'unmatched_color': '#FF6600'}) == []
        assert st.validate_global_config({'unmatched_color': None}) == []
        (p,) = st.validate_global_config({'unmatched_color': 'redd'})
        assert 'not a color' in p

    def test_init_color_null(self):
        assert st.validate_global_config({'init_color': None}) == []

    def test_not_a_mapping(self):
        assert st.validate_global_config(['a']) == ['top level is not a mapping']


class TestGlobalConfigFile:
    def test_missing_file(self, tmp_path):
        (c,) = st.check_global_config(str(tmp_path / 'defaults.yaml'), yaml)
        assert c.status == st.OK and 'stock defaults' in c.detail

    def test_yaml_error_fails(self, tmp_path):
        p = tmp_path / 'defaults.yaml'
        p.write_text('tag_position: [unclosed\n')
        (c,) = st.check_global_config(str(p), yaml)
        assert c.status == st.FAIL and 'YAML error' in c.detail

    def test_problems_listed(self, tmp_path):
        p = tmp_path / 'defaults.yaml'
        p.write_text('tag_position: left\nfoo: 1\n')
        head, *rest = st.check_global_config(str(p), yaml)
        assert head.status == st.WARN and '2 problem' in head.detail
        assert [c.status for c in rest] == [st.WARN, st.WARN]

    def test_valid(self, tmp_path):
        p = tmp_path / 'defaults.yaml'
        p.write_text('tag_position: after\n')
        assert [c.status for c in st.check_global_config(str(p), yaml)] == [st.OK]


class TestPackageConfigs:
    def _pkg(self, prefix, name, text):
        d = prefix / 'share' / name / 'config'
        d.mkdir(parents=True)
        (d / 'dendROS.yaml').write_text(text)

    def test_found_across_prefixes_first_wins(self, tmp_path):
        a, b = tmp_path / 'a', tmp_path / 'b'
        self._pkg(a, 'nav', 'groups: {}\n')
        self._pkg(b, 'nav', 'groups: {}\n')
        self._pkg(b, 'loc', 'groups: {}\n')
        (b / 'share' / 'noconf').mkdir()
        found = st.find_package_configs(env={'AMENT_PREFIX_PATH': f'{a}:{b}:/nope'})
        assert [p for p, _ in found] == ['nav', 'loc']
        assert found[0][1].startswith(str(a))

    def test_none(self):
        (c,) = st.check_package_configs([], loader=None)
        assert c.status == st.INFO

    def test_broken_config_fails(self, tmp_path):
        from lib.config_loader import load_config
        self._pkg(tmp_path, 'good', 'groups:\n  g:\n    color: red\n    nodes: [a]\n')
        self._pkg(tmp_path, 'bad', 'groups: [\n')
        found = st.find_package_configs(env={'AMENT_PREFIX_PATH': str(tmp_path)})
        head, broken = st.check_package_configs(found, load_config)
        assert head.status == st.FAIL and '2 found' in head.detail
        assert broken.detail.startswith('bad:')


class TestTerminalChecks:
    def test_term(self):
        assert st.check_term(env={'TERM': 'xterm-256color'}).status == st.OK
        assert st.check_term(env={'TERM': 'dumb'}).status == st.WARN
        assert 'COLORTERM=truecolor' in st.check_term(
            env={'TERM': 'xterm', 'COLORTERM': 'truecolor'}).detail

    def test_truecolor(self):
        assert st.truecolor_check(env={'COLORTERM': '24bit'}).status == st.OK
        assert st.truecolor_check(env={}).status == st.INFO

    def test_probe_skipped_and_error(self):
        assert st.curses_probe_checks({'skipped': 'x'})[0].status == st.INFO
        (c,) = st.curses_probe_checks({'error': 'boom'})
        assert c.status == st.FAIL and 'classic' in c.detail

    @pytest.mark.parametrize('ncolors,console,statuses', [
        (256, 'exact', [st.OK, st.OK, st.OK]),
        (256, 'stock', [st.OK, st.OK, st.INFO]),
        (8, 'base', [st.OK, st.WARN, st.INFO]),
        (0, 'base', [st.OK, st.WARN, st.INFO]),
    ])
    def test_probe_results(self, ncolors, console, statuses):
        info = {'rows': 24, 'cols': 80, 'colors': ncolors, 'pairs': 64, 'console': console}
        assert [c.status for c in st.curses_probe_checks(info)] == statuses


class TestReport:
    def test_summary_and_exit_code(self):
        checks = [st.Check(st.OK, '', ''), st.Check(st.WARN, '', ''), st.Check(st.INFO, '', '')]
        assert st.summarize(checks) == ('1 ok, 1 warning, 0 failed', 0)
        checks.append(st.Check(st.FAIL, '', ''))
        assert st.summarize(checks)[1] == 1

    def test_format_check_marks(self):
        line = st.format_check(st.Check(st.FAIL, 'ros2', 'not found'))
        assert_segment_colored(line, '\u2718', '31;1')
        assert strip_ansi(line).split() == ['\u2718', 'ros2', 'not', 'found']


class TestColorCharts:
    def test_named_table_uses_resolved_codes(self):
        rows = charts.named_color_table()
        assert len(rows) == 1 + 8
        red = rows[2]
        assert_segment_colored(red, 'red     ', '31')
        assert_segment_colored(red, 'red     ', '91')
        assert_segment_colored(red, 'red     ', '31;1')
        assert_segment_colored(red, 'red     ', '31;2')
        assert_segment_colored(red, '[TAG]', '31;7')

    def test_named_table_honours_ignore_bold(self):
        set_ignore_bold(True)
        try:
            row = charts.named_color_table()[2]
        finally:
            set_ignore_bold(False)
        assert '\033[31;1m' not in row

    def test_extended_grid_exact_and_tui_swatches(self):
        rows = charts.extended_color_grid(per_row=4)
        text = strip_ansi('\n'.join(rows))
        assert 'grey/gray' in text and text.count('gray') == 1
        teal = next(r for r in rows if 'teal' in r)
        assert_segment_colored(teal, '\u2588\u2588', '38;2;0;128;128')
        assert_segment_colored(teal, '\u2588\u2588', f'38;5;{quantize_rgb_to_256(0, 128, 128)}')

    def test_palette_256_covers_every_index(self):
        joined = '\n'.join(charts.palette_256())
        for i in range(256):
            assert f'48;5;{i}' in joined

    def test_gradient_width_and_endpoints(self):
        rows = charts.truecolor_gradients(40)
        assert len(rows) == 5
        assert all(strip_ansi(r) == '  ' + '\u2580' * 40 for r in rows)
        brand = rows[-1]
        assert brand.count('38;2;0;75;107') >= 1 and '38;2;224;127;0' in brand

    def test_text_attributes(self):
        (row,) = charts.text_attributes()
        assert_segment_colored(row, 'dim', '2')
        assert_segment_colored(row, 'reverse', '7')

    def test_bold_brightness_rows(self):
        (row,) = charts.bold_brightness_rows()
        assert_segment_colored(row, 'blue', '34;1')
        assert_segment_colored(row, '[TAG]', '34;1;7')


class TestSamplePreview:
    def _plain(self, cfg):
        return [strip_ansi(r).strip() for r in charts.sample_preview(cfg)]

    def test_before_inverted_without_metadata(self):
        cfg = {'tag_position': 'before', 'tag_style': 'inverted',
               'show_timestamp': False, 'show_logger_name': False}
        rows = charts.sample_preview(cfg)
        assert self._plain(cfg)[1] == ('[NAV] [controller_server-1] [INFO]: '
                                       'Controller frequency set to 20.0Hz')
        assert_segment_colored(rows[1], '[NAV]', _resolve_color('cyan') + ';7')

    def test_after_with_metadata(self):
        plain = self._plain({'tag_position': 'after'})
        assert plain[2].startswith('[amcl-2] [LOC] [WARN] [1763460000.341] [amcl]:')

    def test_no_tag_no_launch_msgs(self):
        plain = self._plain({'show_tag_launch': False, 'colorize_launch_msgs': False})
        assert len(plain) == 3 and not any('[NAV]' in p for p in plain)

    def test_full_line(self):
        rows = charts.sample_preview({'color_mode': 'full_line', 'tag_position': 'before',
                                      'show_tag_launch': False})
        assert rows[-1].startswith('  \033[' + _resolve_color('green') + 'm[lidar_driver-3]')


class TestEntryPoint:
    def test_runs_without_a_terminal(self, tmp_path):
        env = dict(os.environ, HOME=str(tmp_path), AMENT_PREFIX_PATH='')
        r = subprocess.run([sys.executable, os.path.join(REPO_ROOT, 'dendROS', 'dendros_selftest.py')],
                           capture_output=True, text=True, env=env, timeout=60, stdin=subprocess.DEVNULL)
        out = strip_ansi(r.stdout)
        for title in ('Dependencies', 'Shell and config', 'Terminal', 'Named colors',
                      '24-bit gradients', 'Preview with your settings'):
            assert title in out
        assert 'needs an interactive terminal' in out
        assert '[dendROS]' in out.splitlines()[-1]
