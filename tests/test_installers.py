"""Installer regression checks; no root or network needed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = [ROOT / 'scripts' / f'build_and_install_{name}.sh'
              for name in ('arch', 'ubuntu')]


class InstallerTests(unittest.TestCase):
    def run_function(self, installer, code, *args, env=None):
        return subprocess.run(
            ['bash', '-c', 'source "$1"; shift; ' + code, 'test', str(installer), *map(str, args)],
            capture_output=True, text=True, timeout=15, env=env)

    def test_invalid_arguments(self):
        for installer in INSTALLERS:
            for args in (('--jobs', '0'), ('--jobs', '-1'), ('--jobs',),
                         ('--version',), ('--version', '../../tmp'),
                         ('--from-cache', '--rebuild'), ('--restore', '--check')):
                with self.subTest(installer=installer.name, args=args):
                    result = self.run_function(installer, 'parse_args "$@"; validate_build_args', *args)
                    self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_incomplete_or_stale_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cli = cache / 'usr/bin/kicad-cli'
            cli.parent.mkdir(parents=True)
            cli.touch(mode=0o755)
            for installer in INSTALLERS:
                for meta in ('', 'version=10.0.7\npatches_hash=wrong\ncache_format=wrong\n'):
                    (cache / '.meta').write_text(meta)
                    result = self.run_function(installer, 'cache_is_complete "$1" 10.0.7 testhash', cache)
                    self.assertNotEqual(result.returncode, 0)
                result = self.run_function(installer, '''
                    printf 'version=10.0.7\npatches_hash=testhash\ncache_format=%s\n' "$CACHE_FORMAT_VERSION" > "$1/.meta"
                    cache_is_complete "$1" 10.0.7 testhash
                ''', cache)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_requires_exit_status_version_and_converted_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / 'kicad-cli'
            cli.write_text('''#!/bin/bash
if [[ "$1" == version ]]; then
    echo "${TEST_VERSION:-10.0.7}"
    exit "${TEST_VERSION_STATUS:-0}"
fi
[[ "${TEST_IMPORT_STATUS:-0}" == 0 ]] || exit "$TEST_IMPORT_STATUS"
while [[ $# -gt 0 ]]; do
    if [[ "$1" == -o ]]; then
        [[ "${TEST_NO_OUTPUT:-0}" == 1 ]] || printf '(kicad_symbol_lib (symbol "test"))\n' > "$2"
        exit 0
    fi
    shift
done
exit 1
''')
            cli.chmod(0o755)
            for installer in INSTALLERS:
                cases = [({}, 0), ({'TEST_VERSION': '10.0.7+local'}, 0),
                         ({'TEST_VERSION': '10.0.70'}, 1),
                         ({'TEST_VERSION': '10.0.7-rc1'}, 1),
                         ({'TEST_VERSION_STATUS': '1'}, 1),
                         ({'TEST_IMPORT_STATUS': '139'}, 1),
                         ({'TEST_NO_OUTPUT': '1'}, 1)]
                for overrides, expected in cases:
                    with self.subTest(installer=installer.name, overrides=overrides):
                        result = self.run_function(installer, 'verify_cli "$1" 10.0.7', cli,
                                                   env={**os.environ, **overrides})
                        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_already_applied_patch_is_not_reversed(self):
        for installer in INSTALLERS:
            with self.subTest(installer=installer.name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src, patches = root / 'src', root / 'patches'
                src.mkdir()
                patches.mkdir()
                (src / 'example').write_text('before\n')
                (patches / 'fix.patch').write_text(
                    '--- a/example\n+++ b/example\n@@ -1 +1 @@\n-before\n+after\n')
                result = self.run_function(installer, '''
                    apply_patches "$1" "$2"
                    apply_patches "$1" "$2"
                ''', src, patches)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((src / 'example').read_text(), 'after\n')

    def test_missing_cache_does_not_modify_system_packages(self):
        for installer in INSTALLERS:
            with self.subTest(installer=installer.name), tempfile.TemporaryDirectory() as tmp:
                result = self.run_function(installer, '''
                    CACHE_DIR="$1"
                    check_arch_host() { :; }
                    check_not_root() { :; }
                    offer_release_ppa_if_needed() { touch "$CACHE_DIR/touched"; }
                    install_kicad_base_if_needed() { touch "$CACHE_DIR/touched"; }
                    install_arch_runtime_if_needed() { touch "$CACHE_DIR/touched"; }
                    main --version 10.0.7 --from-cache
                ''', tmp)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((Path(tmp) / 'touched').exists(), result.stdout)

    def test_cached_header_path_is_not_a_cached_runtime_path(self):
        for installer in INSTALLERS:
            with self.subTest(installer=installer.name), tempfile.TemporaryDirectory() as tmp:
                binary = Path(tmp) / 'library'
                binary.write_bytes(b'/test-cache/deps/include/boost/assert.hpp\0/usr/share/kicad\0')
                code = 'CACHE_DIR=/test-cache; runtime_data_path_is_cached "$1"'
                result = self.run_function(installer, code, binary)
                self.assertEqual(result.returncode, 1)
                binary.write_bytes(b'/test-cache/stage/usr/share/kicad\0')
                result = self.run_function(installer, code, binary)
                self.assertEqual(result.returncode, 0)

    def test_arch_runtime_install_refreshes_with_full_upgrade(self):
        for installed in ('true', 'false'):
            with self.subTest(installed=installed), tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / 'pacman-args'
                result = self.run_function(INSTALLERS[0], '''
                    command_log="$1"
                    installed="$2"
                    package_installed() { "$installed"; }
                    arch_installed_package_version() { echo 10.0.6-1; }
                    run_sudo() { printf '%s\n' "$@" > "$command_log"; }
                    install_arch_runtime_if_needed 10.0.7
                ''', log, installed)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = log.read_text().splitlines()
                self.assertEqual(args[:3], ['pacman', '-Syu', '--needed'])
                self.assertIn('kicad-library', args)
                self.assertIn('kicad-library-3d', args)
                self.assertNotIn('--noconfirm', args)
                if installed == 'false':
                    self.assertIn('kicad', args)

    def test_arch_package_failure_stops_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'continued'
            result = self.run_function(INSTALLERS[0], '''
                run_sudo() { return 1; }
                install_arch_packages boost
                touch "$1"
            ''', marker)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_arch_cache_is_checked_after_packages_before_system_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'steps'
            result = self.run_function(INSTALLERS[0], '''
                CACHE_DIR="$1"
                step_log="$2"
                check_arch_host() { :; }
                check_not_root() { :; }
                cache_is_complete() { return 0; }
                install_arch_runtime_if_needed() { echo packages >> "$step_log"; }
                find_system_kicad() { echo /usr/bin; }
                verify_cli() { echo verify >> "$step_log"; return 1; }
                backup_originals() { echo backup >> "$step_log"; }
                install_from_cache() { echo install >> "$step_log"; }
                main --version 10.0.7 --from-cache
            ''', tmp, log)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ['packages', 'verify'])


if __name__ == '__main__':
    unittest.main()
