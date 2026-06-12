"""Tests for dendros_init — node extraction, config generation, build file modification."""

import os
import sys
import textwrap

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'dendROS'))

from dendros_init import (
    make_label,
    extract_nodes_from_python,
    extract_nodes_from_xml,
    scan_launch_file,
    collect_nodes,
    write_config,
    merge_config,
    modify_cmake,
    modify_setup_py,
    modify_setup_cfg,
    find_package_root,
    get_package_name,
    main,
)


# ── make_label ────────────────────────────────────────────────────────────────

class TestMakeLabel:
    def test_single_word(self):
        assert make_label('slam') == 'SLA'

    def test_two_words(self):
        label = make_label('slam_toolbox')
        assert label == 'ST'

    def test_three_words(self):
        assert make_label('robot_localization_pkg') == 'RLP'

    def test_strips_digits(self):
        # nav2 → nav (digits stripped) → N
        label = make_label('nav2_bringup')
        assert label == 'NB'

    def test_four_words_capped_at_four(self):
        label = make_label('a_b_c_d_e')
        assert len(label) <= 4

    def test_empty_like_input_falls_back(self):
        label = make_label('123')
        assert isinstance(label, str) and len(label) > 0


# ── extract_nodes_from_python ─────────────────────────────────────────────────

class TestExtractNodesFromPython:
    def test_basic_node(self):
        content = "Node(package='my_pkg', executable='talker', name='my_talker')"
        nodes = extract_nodes_from_python(content)
        assert len(nodes) == 1
        assert nodes[0]['name'] == 'my_talker'
        assert nodes[0]['package'] == 'my_pkg'

    def test_name_takes_priority_over_executable(self):
        content = "Node(package='p', executable='exe', name='explicit_name')"
        nodes = extract_nodes_from_python(content)
        assert nodes[0]['name'] == 'explicit_name'

    def test_falls_back_to_executable_when_no_name(self):
        content = "Node(package='my_pkg', executable='talker')"
        nodes = extract_nodes_from_python(content)
        assert len(nodes) == 1
        assert nodes[0]['name'] == 'talker'
        assert nodes[0]['package'] == 'my_pkg'

    def test_skips_node_with_no_name_or_executable(self):
        content = "Node(package='my_pkg')"
        nodes = extract_nodes_from_python(content)
        assert nodes == []

    def test_dynamic_name_skipped_falls_back_to_executable(self):
        # LaunchConfiguration('n') is not a Constant → _ast_str returns None → uses executable
        content = textwrap.dedent("""\
            from launch.substitutions import LaunchConfiguration
            Node(package='p', executable='exe', name=LaunchConfiguration('n'))
        """)
        nodes = extract_nodes_from_python(content)
        assert len(nodes) == 1
        assert nodes[0]['name'] == 'exe'

    def test_namespace_captured(self):
        content = "Node(package='p', executable='e', name='n', namespace='/my_ns')"
        nodes = extract_nodes_from_python(content)
        assert nodes[0]['namespace'] == '/my_ns'

    def test_composable_node(self):
        content = "ComposableNode(package='p', executable='comp', name='c')"
        nodes = extract_nodes_from_python(content)
        assert len(nodes) == 1
        assert nodes[0]['name'] == 'c'

    def test_multiple_nodes(self):
        content = textwrap.dedent("""\
            Node(package='p1', executable='a', name='node_a')
            Node(package='p2', executable='b', name='node_b')
        """)
        nodes = extract_nodes_from_python(content)
        names = {n['name'] for n in nodes}
        assert names == {'node_a', 'node_b'}

    def test_syntax_error_returns_empty(self):
        nodes = extract_nodes_from_python('def broken(:')
        assert nodes == []

    def test_empty_content_returns_empty(self):
        assert extract_nodes_from_python('') == []


# ── extract_nodes_from_xml ────────────────────────────────────────────────────

class TestExtractNodesFromXml:
    def test_basic_node(self):
        content = '<launch><node pkg="p" exec="talker" name="n"/></launch>'
        nodes = extract_nodes_from_xml(content)
        assert len(nodes) == 1
        assert nodes[0]['name'] == 'n'
        assert nodes[0]['package'] == 'p'

    def test_exec_used_as_fallback_name(self):
        content = '<launch><node pkg="p" exec="talker"/></launch>'
        nodes = extract_nodes_from_xml(content)
        assert len(nodes) == 1
        assert nodes[0]['name'] == 'talker'

    def test_namespace_captured(self):
        content = '<launch><node pkg="p" exec="e" name="n" namespace="/ns"/></launch>'
        nodes = extract_nodes_from_xml(content)
        assert nodes[0]['namespace'] == '/ns'

    def test_package_attribute_alias(self):
        content = '<launch><node package="my_pkg" exec="e" name="n"/></launch>'
        nodes = extract_nodes_from_xml(content)
        assert nodes[0]['package'] == 'my_pkg'

    def test_skips_node_with_no_name_or_exec(self):
        content = '<launch><node pkg="p"/></launch>'
        nodes = extract_nodes_from_xml(content)
        assert nodes == []

    def test_multiple_nodes(self):
        content = textwrap.dedent("""\
            <launch>
              <node pkg="p" exec="a" name="node_a"/>
              <node pkg="q" exec="b" name="node_b"/>
            </launch>
        """)
        nodes = extract_nodes_from_xml(content)
        assert {n['name'] for n in nodes} == {'node_a', 'node_b'}

    def test_malformed_xml_returns_empty(self):
        assert extract_nodes_from_xml('<launch><node broken') == []

    def test_empty_returns_empty(self):
        assert extract_nodes_from_xml('') == []


# ── scan_launch_file ──────────────────────────────────────────────────────────

class TestScanLaunchFile:
    def test_py_file(self, tmp_path):
        f = tmp_path / 'test.launch.py'
        f.write_text("Node(package='p', executable='talker', name='n')")
        nodes = scan_launch_file(str(f))
        assert len(nodes) == 1

    def test_xml_file(self, tmp_path):
        f = tmp_path / 'test.launch.xml'
        f.write_text('<launch><node pkg="p" exec="talker" name="n"/></launch>')
        nodes = scan_launch_file(str(f))
        assert len(nodes) == 1

    def test_unknown_extension_returns_empty(self, tmp_path):
        f = tmp_path / 'test.launch.yaml'
        f.write_text('nodes: []')
        assert scan_launch_file(str(f)) == []

    def test_nonexistent_file_returns_empty(self):
        assert scan_launch_file('/nonexistent/file.py') == []


# ── collect_nodes ─────────────────────────────────────────────────────────────

class TestCollectNodes:
    def test_local_nodes_grouped_by_source_package(self, tmp_path):
        launch_dir = tmp_path / 'launch'
        launch_dir.mkdir()
        (launch_dir / 'test.launch.py').write_text(textwrap.dedent("""\
            Node(package='pkg_a', executable='a', name='node_a')
            Node(package='pkg_b', executable='b', name='node_b')
        """))
        groups = collect_nodes(launch_dir, 'my_bringup')
        assert 'node_a' in groups['pkg_a']
        assert 'node_b' in groups['pkg_b']

    def test_node_without_package_falls_back_to_local_pkg(self, tmp_path):
        launch_dir = tmp_path / 'launch'
        launch_dir.mkdir()
        (launch_dir / 'test.launch.py').write_text(
            "Node(executable='my_exe', name='my_node')"
        )
        groups = collect_nodes(launch_dir, 'my_bringup')
        assert 'my_node' in groups['my_bringup']

    def test_missing_launch_dir_returns_empty(self, tmp_path):
        groups = collect_nodes(tmp_path / 'nonexistent', 'my_pkg')
        assert groups == {}

    def test_recursive_scans_included_packages(self, tmp_path):
        # Set up fake AMENT_PREFIX_PATH
        share = tmp_path / 'share'

        # Local launch file that references pkg2
        launch_dir = tmp_path / 'launch'
        launch_dir.mkdir()
        (launch_dir / 'main.launch.py').write_text(
            "get_package_share_directory('pkg2')\n"
            "Node(package='pkg1', executable='node1', name='node1')\n"
        )

        # pkg2 launch files in the fake install tree
        pkg2_launch = share / 'pkg2' / 'launch'
        pkg2_launch.mkdir(parents=True)
        (pkg2_launch / 'sub.launch.py').write_text(
            "Node(package='pkg2', executable='node2', name='node2')\n"
        )

        orig = os.environ.get('AMENT_PREFIX_PATH', '')
        os.environ['AMENT_PREFIX_PATH'] = str(tmp_path)
        try:
            groups = collect_nodes(launch_dir, 'pkg1', recursive=True)
        finally:
            os.environ['AMENT_PREFIX_PATH'] = orig

        assert 'node1' in groups['pkg1']
        assert 'node2' in groups['pkg2']

    def test_recursive_warns_when_package_not_found(self, tmp_path, capsys):
        # launch dir NOT placed as a sibling, so source-tree fallback also misses
        launch_dir = tmp_path / 'launch'
        launch_dir.mkdir()
        (launch_dir / 'main.launch.py').write_text(
            "get_package_share_directory('missing_pkg')\n"
            "Node(package='my_pkg', executable='n', name='n')\n"
        )

        orig = os.environ.get('AMENT_PREFIX_PATH', '')
        os.environ['AMENT_PREFIX_PATH'] = '/nonexistent_path'
        try:
            groups = collect_nodes(launch_dir, 'my_pkg', recursive=True)
        finally:
            if orig:
                os.environ['AMENT_PREFIX_PATH'] = orig
            else:
                os.environ.pop('AMENT_PREFIX_PATH', None)

        captured = capsys.readouterr()
        assert 'missing_pkg' in captured.err
        assert 'not found' in captured.err
        assert 'n' in groups.get('my_pkg', set())

    def test_recursive_falls_back_to_source_tree(self, tmp_path, capsys):
        # Simulate a colcon workspace: ws/src/my_bringup/launch + ws/src/dep_pkg/launch
        src_dir = tmp_path / 'src'
        bringup_launch = src_dir / 'my_bringup' / 'launch'
        bringup_launch.mkdir(parents=True)
        (bringup_launch / 'main.launch.py').write_text(
            "get_package_share_directory('dep_pkg')\n"
            "Node(package='my_bringup', executable='main', name='main')\n"
        )

        dep_launch = src_dir / 'dep_pkg' / 'launch'
        dep_launch.mkdir(parents=True)
        (dep_launch / 'dep.launch.py').write_text(
            "Node(package='dep_pkg', executable='dep_node', name='dep_node')\n"
        )

        orig = os.environ.get('AMENT_PREFIX_PATH', '')
        os.environ['AMENT_PREFIX_PATH'] = '/nonexistent_path'
        try:
            groups = collect_nodes(bringup_launch, 'my_bringup', recursive=True)
        finally:
            if orig:
                os.environ['AMENT_PREFIX_PATH'] = orig
            else:
                os.environ.pop('AMENT_PREFIX_PATH', None)

        assert 'main' in groups.get('my_bringup', set())
        assert 'dep_node' in groups.get('dep_pkg', set())
        captured = capsys.readouterr()
        assert '[source]' in captured.out

    def test_recursive_warns_when_no_includes_found(self, tmp_path, capsys):
        launch_dir = tmp_path / 'launch'
        launch_dir.mkdir()
        (launch_dir / 'main.launch.py').write_text(
            "Node(package='my_pkg', executable='n', name='n')\n"
        )

        groups = collect_nodes(launch_dir, 'my_pkg', recursive=True)

        captured = capsys.readouterr()
        assert 'no include references' in captured.err


# ── write_config ──────────────────────────────────────────────────────────────

class TestWriteConfig:
    def test_creates_valid_yaml(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'my_pkg': ['talker', 'listener']})
        with open(path) as f:
            data = yaml.safe_load(f)
        assert 'groups' in data
        assert 'my_pkg' in data['groups']

    def test_nodes_are_sorted(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'pkg': ['z_node', 'a_node', 'm_node']})
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data['groups']['pkg']['nodes'] == ['a_node', 'm_node', 'z_node']

    def test_groups_sorted_alphabetically(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'zzz': ['n1'], 'aaa': ['n2']})
        with open(path) as f:
            data = yaml.safe_load(f)
        assert list(data['groups'].keys()) == ['aaa', 'zzz']

    def test_each_group_has_color_no_label(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'nav2_bringup': ['node_a']})
        with open(path) as f:
            data = yaml.safe_load(f)
        grp = data['groups']['nav2_bringup']
        assert 'color' in grp
        assert 'label' not in grp

    def test_null_color_when_palette_disabled(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'pkg_a': ['n1'], 'pkg_b': ['n2']}, use_palette=False)
        with open(path) as f:
            data = yaml.safe_load(f)
        for grp in data['groups'].values():
            assert grp['color'] is None

    def test_groups_use_distinct_colors(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'pkg_a': ['n1'], 'pkg_b': ['n2'], 'pkg_c': ['n3']})
        with open(path) as f:
            data = yaml.safe_load(f)
        colors = [g['color'] for g in data['groups'].values()]
        assert len(set(colors)) == len(colors)

    def test_defaults_section_present(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'pkg': ['n']})
        with open(path) as f:
            data = yaml.safe_load(f)
        assert 'defaults' in data
        assert data['defaults']['color_mode'] == 'tag_only'

    def test_empty_groups_writes_valid_yaml(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {})
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data.get('groups') in (None, {})

    def test_use_bold_prefixes_colors(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'pkg_a': ['n1'], 'pkg_b': ['n2']}, use_bold=True)
        with open(path) as f:
            data = yaml.safe_load(f)
        for grp in data['groups'].values():
            assert grp['color'].startswith('bold ')

    def test_use_bold_false_does_not_add_bold(self, tmp_path):
        path = str(tmp_path / 'dendROS.yaml')
        write_config(path, {'pkg_a': ['n1']}, use_bold=False)
        with open(path) as f:
            data = yaml.safe_load(f)
        color = data['groups']['pkg_a']['color']
        # The first palette color is 'blue' — should stay plain
        assert color == 'blue'

    def test_use_bold_skips_already_bold(self, tmp_path):
        # A palette entry that already contains 'bold' should not be double-bolded
        from dendros_init import _bold_color
        assert _bold_color('bold magenta') == 'bold magenta'

    def test_use_bold_null_color_unchanged(self, tmp_path):
        from dendros_init import _bold_color
        assert _bold_color('null') == 'null'


# ── merge_config ──────────────────────────────────────────────────────────────

class TestMergeConfig:
    def _make_config(self, tmp_path, nodes_by_group):
        path = tmp_path / 'dendROS.yaml'
        groups = {
            pkg: {'color': 'blue', 'label': 'T', 'nodes': list(ns)}
            for pkg, ns in nodes_by_group.items()
        }
        path.write_text(yaml.dump({'groups': groups}))
        return str(path)

    def test_adds_new_nodes(self, tmp_path):
        path = self._make_config(tmp_path, {'pkg_a': ['existing_node']})
        added = merge_config(path, {'pkg_a': ['new_node']})
        assert added == 1
        with open(path) as f:
            data = yaml.safe_load(f)
        assert 'new_node' in data['groups']['pkg_a']['nodes']
        assert 'existing_node' in data['groups']['pkg_a']['nodes']

    def test_skips_already_present_nodes(self, tmp_path):
        path = self._make_config(tmp_path, {'pkg_a': ['existing']})
        added = merge_config(path, {'pkg_a': ['existing']})
        assert added == 0

    def test_adds_new_group(self, tmp_path):
        path = self._make_config(tmp_path, {'pkg_a': ['n1']})
        added = merge_config(path, {'pkg_b': ['n2']})
        assert added == 1
        with open(path) as f:
            data = yaml.safe_load(f)
        assert 'pkg_b' in data['groups']
        assert 'n2' in data['groups']['pkg_b']['nodes']

    def test_returns_zero_when_nothing_new(self, tmp_path):
        path = self._make_config(tmp_path, {'pkg_a': ['n1', 'n2']})
        assert merge_config(path, {'pkg_a': ['n1', 'n2']}) == 0

    def test_new_group_has_no_label(self, tmp_path):
        path = self._make_config(tmp_path, {'pkg_a': ['n1']})
        merge_config(path, {'pkg_b': ['n2']})
        with open(path) as f:
            data = yaml.safe_load(f)
        assert 'label' not in data['groups']['pkg_b']

    def test_new_group_use_bold(self, tmp_path):
        path = self._make_config(tmp_path, {'pkg_a': ['n1']})
        merge_config(path, {'pkg_b': ['n2']}, use_bold=True)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data['groups']['pkg_b']['color'].startswith('bold ')


# ── modify_cmake ──────────────────────────────────────────────────────────────

class TestModifyCmake:
    def test_adds_install_before_ament_package(self, tmp_path):
        cmake = tmp_path / 'CMakeLists.txt'
        cmake.write_text('cmake_minimum_required(VERSION 3.5)\nament_package()\n')
        assert modify_cmake(str(cmake)) is True
        content = cmake.read_text()
        assert 'install(DIRECTORY config/' in content
        # Block must appear before ament_package()
        assert content.index('install(DIRECTORY') < content.index('ament_package()')

    def test_appends_when_no_ament_package(self, tmp_path):
        cmake = tmp_path / 'CMakeLists.txt'
        cmake.write_text('cmake_minimum_required(VERSION 3.5)\n')
        assert modify_cmake(str(cmake)) is True
        assert 'install(DIRECTORY config/' in cmake.read_text()

    def test_skips_when_config_already_installed(self, tmp_path):
        cmake = tmp_path / 'CMakeLists.txt'
        cmake.write_text(
            'install(DIRECTORY config/ DESTINATION share/${PROJECT_NAME})\nament_package()\n'
        )
        assert modify_cmake(str(cmake)) is False

    def test_idempotent(self, tmp_path):
        cmake = tmp_path / 'CMakeLists.txt'
        cmake.write_text('cmake_minimum_required(VERSION 3.5)\nament_package()\n')
        modify_cmake(str(cmake))
        first = cmake.read_text()
        assert modify_cmake(str(cmake)) is False
        assert cmake.read_text() == first


# ── modify_setup_py ───────────────────────────────────────────────────────────

class TestModifySetupPy:
    _TEMPLATE = textwrap.dedent("""\
        import os
        from setuptools import setup
        package_name = 'my_pkg'
        setup(
            name=package_name,
            data_files=[
                ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
                ('share/' + package_name, ['package.xml']),
            ],
        )
    """)

    def test_adds_config_entry(self, tmp_path):
        f = tmp_path / 'setup.py'
        f.write_text(self._TEMPLATE)
        assert modify_setup_py(str(f), 'my_pkg') is True
        assert "config/dendROS.yaml" in f.read_text()

    def test_skips_when_already_present(self, tmp_path):
        content = self._TEMPLATE.replace(
            "('share/' + package_name, ['package.xml']),",
            "('share/' + package_name, ['package.xml']),\n"
            "        (os.path.join('share', 'my_pkg', 'config'), ['config/dendROS.yaml']),",
        )
        f = tmp_path / 'setup.py'
        f.write_text(content)
        assert modify_setup_py(str(f), 'my_pkg') is False

    def test_returns_false_when_no_data_files(self, tmp_path):
        f = tmp_path / 'setup.py'
        f.write_text('from setuptools import setup\nsetup(name="x")\n')
        assert modify_setup_py(str(f), 'my_pkg') is False

    def test_adds_os_import_if_missing(self, tmp_path):
        content = self._TEMPLATE.replace('import os\n', '')
        f = tmp_path / 'setup.py'
        f.write_text(content)
        modify_setup_py(str(f), 'my_pkg')
        assert 'import os' in f.read_text()


# ── modify_setup_cfg ──────────────────────────────────────────────────────────

class TestModifySetupCfg:
    _WITH_SECTION = textwrap.dedent("""\
        [metadata]
        name = my_pkg

        [options.data_files]
        share/ament_index/resource_index/packages =
            resource/my_pkg
        share/my_pkg =
            package.xml
    """)

    def test_adds_to_existing_section(self, tmp_path):
        f = tmp_path / 'setup.cfg'
        f.write_text(self._WITH_SECTION)
        assert modify_setup_cfg(str(f), 'my_pkg') is True
        content = f.read_text()
        assert 'share/my_pkg/config' in content
        assert 'dendROS.yaml' in content

    def test_creates_section_when_missing(self, tmp_path):
        f = tmp_path / 'setup.cfg'
        f.write_text('[metadata]\nname = my_pkg\n')
        assert modify_setup_cfg(str(f), 'my_pkg') is True
        content = f.read_text()
        assert '[options.data_files]' in content
        assert 'dendROS.yaml' in content

    def test_skips_when_already_present(self, tmp_path):
        content = self._WITH_SECTION + 'share/my_pkg/config =\n    config/dendROS.yaml\n'
        f = tmp_path / 'setup.cfg'
        f.write_text(content)
        assert modify_setup_cfg(str(f), 'my_pkg') is False


# ── find_package_root / get_package_name ─────────────────────────────────────

class TestPackageDetection:
    def test_find_root_from_package_dir(self, tmp_path):
        (tmp_path / 'package.xml').write_text('<package><name>p</name></package>')
        assert find_package_root(cwd=tmp_path) == tmp_path

    def test_find_root_from_subdirectory(self, tmp_path):
        (tmp_path / 'package.xml').write_text('<package><name>p</name></package>')
        sub = tmp_path / 'src' / 'module'
        sub.mkdir(parents=True)
        assert find_package_root(cwd=sub) == tmp_path

    def test_returns_none_when_no_package_xml(self, tmp_path):
        assert find_package_root(cwd=tmp_path) is None

    def test_get_package_name(self, tmp_path):
        (tmp_path / 'package.xml').write_text(
            '<?xml version="1.0"?><package format="3"><name>my_robot</name></package>'
        )
        assert get_package_name(tmp_path) == 'my_robot'

    def test_get_package_name_malformed(self, tmp_path):
        (tmp_path / 'package.xml').write_text('not xml {{')
        assert get_package_name(tmp_path) is None


# ── end-to-end: main() ────────────────────────────────────────────────────────

class TestInitMain:
    def _make_package(self, tmp_path, extra_launch=''):
        (tmp_path / 'package.xml').write_text(
            '<package format="3"><name>my_bringup</name></package>'
        )
        (tmp_path / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.5)\nament_package()\n'
        )
        launch_dir = tmp_path / 'launch'
        launch_dir.mkdir()
        (launch_dir / 'main.launch.py').write_text(textwrap.dedent(f"""\
            Node(package='my_bringup', executable='ctrl', name='controller')
            Node(package='nav2_bringup', executable='nav', name='nav_node')
            {extra_launch}
        """))

    def test_creates_config_and_modifies_cmake(self, tmp_path, monkeypatch):
        self._make_package(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('HOME', str(tmp_path))
        main([])

        config_path = tmp_path / 'config' / 'dendROS.yaml'
        assert config_path.exists()
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert 'my_bringup' in data['groups']
        assert 'controller' in data['groups']['my_bringup']['nodes']
        assert 'nav2_bringup' in data['groups']
        assert 'nav_node' in data['groups']['nav2_bringup']['nodes']

        cmake = (tmp_path / 'CMakeLists.txt').read_text()
        assert 'install(DIRECTORY config/' in cmake

    def test_aborts_when_config_exists(self, tmp_path, monkeypatch):
        self._make_package(tmp_path)
        config_dir = tmp_path / 'config'
        config_dir.mkdir()
        (config_dir / 'dendROS.yaml').write_text('groups: {}\n')

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('HOME', str(tmp_path))
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code != 0

    def test_overwrite_when_configured(self, tmp_path, monkeypatch):
        self._make_package(tmp_path)
        config_dir = tmp_path / 'config'
        config_dir.mkdir()
        (config_dir / 'dendROS.yaml').write_text('groups: {old: {color: red, nodes: [old_node]}}\n')

        # Write global config with overwrite setting
        cfg_dir = tmp_path / '.config' / 'dendROS'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'defaults.yaml').write_text('init_on_existing: overwrite\n')

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('HOME', str(tmp_path))
        main([])

        with open(config_dir / 'dendROS.yaml') as f:
            data = yaml.safe_load(f)
        assert 'old' not in data.get('groups', {})
        assert 'my_bringup' in data['groups']

    def test_merge_adds_new_nodes_only(self, tmp_path, monkeypatch):
        self._make_package(tmp_path)
        config_dir = tmp_path / 'config'
        config_dir.mkdir()
        (config_dir / 'dendROS.yaml').write_text(
            'groups:\n  my_bringup:\n    color: blue\n    nodes:\n      - controller\n'
        )

        cfg_dir = tmp_path / '.config' / 'dendROS'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'defaults.yaml').write_text('init_on_existing: merge\n')

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('HOME', str(tmp_path))
        main([])

        with open(config_dir / 'dendROS.yaml') as f:
            data = yaml.safe_load(f)
        # controller was already there — should still be there
        assert 'controller' in data['groups']['my_bringup']['nodes']
        # nav_node is new
        assert 'nav_node' in data['groups']['nav2_bringup']['nodes']

    def test_init_modify_build_false_skips_cmake(self, tmp_path, monkeypatch):
        self._make_package(tmp_path)

        cfg_dir = tmp_path / '.config' / 'dendROS'
        cfg_dir.mkdir(parents=True)
        (cfg_dir / 'defaults.yaml').write_text('init_modify_build: false\n')

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('HOME', str(tmp_path))
        main([])

        cmake = (tmp_path / 'CMakeLists.txt').read_text()
        assert 'install(DIRECTORY config/' not in cmake

    def test_no_launch_dir_creates_empty_config(self, tmp_path, monkeypatch):
        (tmp_path / 'package.xml').write_text(
            '<package format="3"><name>no_launch_pkg</name></package>'
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('HOME', str(tmp_path))
        main([])
        assert (tmp_path / 'config' / 'dendROS.yaml').exists()

    def test_setup_py_is_modified(self, tmp_path, monkeypatch):
        self._make_package(tmp_path)
        setup_py = tmp_path / 'setup.py'
        setup_py.write_text(textwrap.dedent("""\
            import os
            from setuptools import setup
            package_name = 'my_bringup'
            setup(
                name=package_name,
                data_files=[
                    ('share/' + package_name, ['package.xml']),
                ],
            )
        """))

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv('HOME', str(tmp_path))
        main([])

        assert 'config/dendROS.yaml' in setup_py.read_text()
