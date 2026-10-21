import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('installer', Path(__file__).resolve().parents[1] / 'scripts/installer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orbit home ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bindings = self.home / '.config/hypr/bindings.lua'
        self.bindings.parent.mkdir(parents=True)
        self.original = '-- Personal config\no.bind("SUPER + X", "Editor", "editor")\n'
        self.bindings.write_text(self.original)
        self.deps = patch.object(installer, 'check_dependencies')
        self.deps.start()
        self.addCleanup(self.deps.stop)
        self.commands = []
        self.command_patch = patch.object(installer, 'run', side_effect=self.run_command)
        self.command_patch.start()
        self.addCleanup(self.command_patch.stop)

    def run_command(self, *args, **kwargs):
        self.commands.append(args)
        output = '[]' if args == ('hyprctl', 'binds', '-j') else ''
        return subprocess.CompletedProcess(args, 1 if 'is-active' in args or 'is-enabled' in args else 0, output, '')

    def test_reinstall_and_uninstall_preserve_personal_settings(self):
        installer.install(self.home, gesture=True)
        first = self.bindings.read_text()
        installer.install(self.home, gesture=True)
        self.assertEqual(self.bindings.read_text(), first)
        self.assertEqual(first.count(installer.START), 1)
        self.assertEqual(len(list(self.bindings.parent.glob('*.bak.orbit.*'))), 1)
        # Changes made by the user after installation must survive uninstall.
        self.bindings.write_text(first + '-- Later personal setting\n')
        installer.install(self.home, remove=True)
        self.assertEqual(self.bindings.read_text(), self.original + '-- Later personal setting\n')
        self.assertFalse((self.home / '.local/bin/orbit').is_symlink())
        self.assertFalse((self.home / '.config/systemd/user/orbit.service').exists())
        installer.install(self.home, remove=True)

    def test_collision_has_no_partial_changes(self):
        desktop = self.home / '.local/share/applications/dev.orbit.Converter.desktop'
        desktop.parent.mkdir(parents=True)
        desktop.write_text('User-owned application')
        with self.assertRaisesRegex(RuntimeError, 'unrelated file'):
            installer.install(self.home, gesture=True)
        self.assertFalse((self.home / '.local/bin/orbit').exists())
        self.assertEqual(desktop.read_text(), 'User-owned application')
        self.assertEqual(self.bindings.read_text(), self.original)

    def test_service_failure_restores_all_files(self):
        def fail_restart(*args, **kwargs):
            if args == ('systemctl', '--user', 'restart', 'orbit.service'):
                raise subprocess.CalledProcessError(1, args)
            return self.run_command(*args, **kwargs)
        with patch.object(installer, 'run', side_effect=fail_restart):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.install(self.home, gesture=True)
        self.assertEqual(self.bindings.read_text(), self.original)
        self.assertFalse((self.home / '.local/bin/orbit').is_symlink())
        self.assertFalse((self.home / '.config/systemd/user/orbit.service').exists())
        self.assertIn(('systemctl', '--user', 'stop', 'orbit.service'), self.commands)

    def test_config_validation_failure_rolls_back(self):
        def config_error(*args, **kwargs):
            if args == ('hyprctl', 'configerrors'):
                return subprocess.CompletedProcess(args, 0, 'Invalid binding', '')
            return self.run_command(*args, **kwargs)
        with patch.object(installer, 'run', side_effect=config_error):
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                installer.install(self.home, gesture=True)
        self.assertEqual(self.bindings.read_text(), self.original)
        self.assertFalse((self.home / '.local/bin/orbit').is_symlink())

    def test_shift_conflict_prevents_installation(self):
        with patch.object(installer, 'run', return_value=subprocess.CompletedProcess([], 0, '[{"key":"Shift_L","description":"Personal shortcut"}]', '')):
            with self.assertRaisesRegex(RuntimeError, 'Existing Shift bindings'):
                installer.install(self.home, gesture=True)
        self.assertEqual(self.bindings.read_text(), self.original)
        self.assertFalse((self.home / '.local/bin/orbit').is_symlink())

    def test_malformed_markers_are_not_destroyed(self):
        for text in (installer.START, installer.END, installer.END + installer.START, installer.block() * 2):
            with self.assertRaisesRegex(RuntimeError, 'Malformed'):
                installer.update_bindings(text)

    def test_missing_dependency_is_reported_before_writes(self):
        with patch.object(installer, 'check_dependencies', side_effect=RuntimeError('Missing dependencies: python-gobject')):
            with self.assertRaisesRegex(RuntimeError, 'python-gobject'):
                installer.install(self.home)
        self.assertFalse((self.home / '.local/bin/orbit').exists())

    def test_uninstall_refuses_user_replacement(self):
        installer.install(self.home)
        launcher = self.home / '.local/bin/orbit'
        launcher.unlink()
        launcher.write_text('Personal launcher')
        with self.assertRaisesRegex(RuntimeError, 'unrelated file'):
            installer.install(self.home, remove=True)
        self.assertEqual(launcher.read_text(), 'Personal launcher')

    def test_quoted_home_path_in_desktop_and_service(self):
        installer.install(self.home, gesture=True)
        desktop = (self.home / '.local/share/applications/dev.orbit.Converter.desktop').read_text()
        self.assertIn(f'Exec="{self.home}/.local/bin/orbit" %F', desktop)
        self.assertIn('%%', installer.quote('/home/percent%/orbit'))
        self.assertIn('$$', installer.quote('/home/dollar$/orbit'))


if __name__ == '__main__':
    unittest.main()
