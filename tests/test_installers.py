"""Installer regression checks; no root or network needed."""
import os
import pty
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = [ROOT / 'scripts' / f'build_and_install_{name}.sh'
              for name in ('arch', 'ubuntu')]


class InstallerTests(unittest.TestCase):
    def run_function(self, installer, code, *args, env=None, input=None):
        return subprocess.run(
            ['bash', '-c', 'source "$1"; shift; ' + code, 'test', str(installer), *map(str, args)],
            capture_output=True, text=True, timeout=15, env=env, input=input)

    def test_default_version_is_latest_stable_supported_series(self):
        for installer in INSTALLERS:
            with self.subTest(installer=installer.name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for version in ('10.0.7', '10.0.8', '10.0.10', '10.0.11-rc1'):
                    patches = root / ('kicad-' + version)
                    patches.mkdir()
                    (patches / 'fix.patch').write_text('placeholder\n')
                (root / 'kicad-11.0.0').mkdir()  # Empty series isn't supported.
                result = self.run_function(installer, '''
                    PATCHES_DIR="$1"
                    latest_supported_patch_version
                ''', root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '10.0.10')

    def test_main_selects_new_series_but_preserves_override_and_restore(self):
        for installer in INSTALLERS:
            for args, expected in ((('--check',), '10.0.8'),
                                   (('--check', '--version', '10.0.7'), '10.0.7'),
                                   (('--restore',), '10.0.7')):
                with self.subTest(installer=installer.name, args=args), tempfile.TemporaryDirectory() as tmp:
                    marker = Path(tmp) / 'selected-version'
                    result = self.run_function(installer, '''
                        selected_version_file="$1"; shift
                        check_arch_host() { :; }
                        check_not_root() { :; }
                        report_default_version_context() { :; }
                        report_arch_packages() { :; }
                        detect_kicad_version() { echo 10.0.7; }
                        detect_restore_version() { echo 10.0.7; }
                        find_system_kicad() { echo /usr/bin; }
                        cache_is_complete() { return 1; }
                        restore_originals() { echo "$1" > "$selected_version_file"; }
                        prepare_patch_check_source() {
                            echo "$1" > "$selected_version_file"
                            PATCH_CHECK_SRC=/unused
                        }
                        apply_patches() { :; }
                        main "$@"
                    ''', marker, *args)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(marker.read_text().strip(), expected)

    def test_patch_context_mismatch_is_rejected_without_fuzz(self):
        for installer in INSTALLERS:
            with self.subTest(installer=installer.name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src, patches = root / 'src', root / 'patches'
                src.mkdir()
                patches.mkdir()
                (src / 'example').write_text('different\nbefore\ncontext\n')
                (patches / 'fix.patch').write_text(
                    '--- a/example\n+++ b/example\n@@ -1,3 +1,3 @@\n'
                    ' original\n-before\n+after\n context\n')
                result = self.run_function(installer, 'apply_patches "$1" "$2" true', src, patches)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual((src / 'example').read_text(), 'different\nbefore\ncontext\n')

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

    def test_arch_pin_preserves_config_backup_and_is_idempotent(self):
        if not shutil.which('pacman-conf'):
            self.skipTest('Requires pacman-conf')
        for directive in ('', 'IgnorePkg = cursor-bin\n', 'IgnorePkg = kicad*\n'):
            with self.subTest(directive=directive), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                included = root / 'included.conf'
                included.write_text('IgnorePkg = another-package\n')
                config = root / 'pacman.conf'
                original = ('# keep comments\n[options]\n' + directive
                            + f'Include = {included}\n[custom]\nServer = https://example.invalid\n')
                config.write_text(original)
                config.chmod(0o640)
                result = self.run_function(INSTALLERS[0], '''
                    run_sudo() { "$@"; }
                    block_kicad_updates "$1"
                    block_kicad_updates "$1"
                ''', config)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                backups = list(root.glob('pacman.conf.before-kicad-pin-*'))
                if 'kicad*' in directive:
                    self.assertEqual(config.read_text(), original)
                    self.assertEqual(backups, [])
                else:
                    self.assertEqual(config.read_text(), original.replace(
                        '[options]\n', '[options]\nIgnorePkg = kicad\n'))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(backups[0].read_text(), original)
                self.assertEqual(config.stat().st_mode & 0o777, 0o640)
                self.assertEqual(included.read_text(), 'IgnorePkg = another-package\n')
                self.assertEqual(list(root.glob('.pacman.conf.kicad-*')), [])

    def test_arch_pin_rejects_invalid_configuration(self):
        if not shutil.which('pacman-conf'):
            self.skipTest('Requires pacman-conf')
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'pacman.conf'
            config.write_text('[custom]\nServer = https://example.invalid\n')
            original = config.read_bytes()
            result = self.run_function(INSTALLERS[0], '''
                run_sudo() { "$@"; }
                block_kicad_updates "$1"
            ''', config)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_bytes(), original)
            self.assertEqual(list(Path(tmp).glob('*.before-kicad-pin-*')), [])

    def test_arch_pin_prompt_requires_interactive_explicit_consent(self):
        for answer, expected in ((b'y\n', True), (b'yes\n', True),
                                 ('да\n'.encode(), True), (b'n\n', False),
                                 (b'\n', False), (b'\x04', False), (None, False)):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as tmp:
                marker = Path(tmp) / 'blocked'
                command = ['bash', '-c', '''
                    source "$1"
                    marker="$2"
                    pacman-conf() { return 0; }
                    block_kicad_updates() { touch "$marker"; }
                    offer_kicad_update_block
                ''', 'test', str(INSTALLERS[0]), str(marker)]
                if answer is None:
                    result = subprocess.run(command, input='y\n', capture_output=True,
                                            text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    master, slave = pty.openpty()
                    try:
                        with subprocess.Popen(command, stdin=slave, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE) as process:
                            os.write(master, answer)
                            out, err = process.communicate(timeout=10)
                            self.assertEqual(process.returncode, 0, out + err)
                    finally:
                        os.close(master)
                        os.close(slave)
                self.assertEqual(marker.exists(), expected)

    def test_arch_already_blocked_or_unreadable_config_skips_prompt(self):
        for query in ('echo kicad', "echo 'kicad*'", 'return 1'):
            with self.subTest(query=query):
                result = self.run_function(INSTALLERS[0], '''
                    eval "pacman-conf() { $1; }"
                    ask() { echo UNEXPECTED_PROMPT; }
                    block_kicad_updates() { echo UNEXPECTED_WRITE; }
                    offer_kicad_update_block
                ''', query)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('UNEXPECTED', result.stdout)

    def test_arch_offers_pin_only_after_successful_installation(self):
        for mode, failure, expected in (
            ('--from-cache', False, ['verify', 'backup', 'install', 'verify-install', 'offer']),
            ('--from-cache', True, ['verify', 'backup', 'install', 'verify-install']),
            ('--build-only', False, []), ('--check', False, []), ('--restore', False, []),
        ):
            with self.subTest(mode=mode, failure=failure), tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / 'steps'
                result = self.run_function(INSTALLERS[0], '''
                    CACHE_DIR="$1"; step_log="$2"; mode="$3"; failure="$4"
                    check_arch_host() { :; }
                    check_not_root() { :; }
                    cache_is_complete() { return 0; }
                    ask() { :; }
                    report_arch_packages() { :; }
                    prepare_patch_check_source() { PATCH_CHECK_SRC=/unused; }
                    apply_patches() { :; }
                    restore_originals() { :; }
                    install_arch_runtime_if_needed() { :; }
                    find_system_kicad() { echo /usr/bin; }
                    verify_cli() { echo verify >> "$step_log"; }
                    backup_originals() { echo backup >> "$step_log"; }
                    install_from_cache() { echo install >> "$step_log"; }
                    verify_installation() {
                        echo verify-install >> "$step_log"
                        if "$failure"; then return 1; fi
                    }
                    offer_kicad_update_block() { echo offer >> "$step_log"; }
                    main --version 10.0.8 "$mode"
                ''', tmp, log, mode, str(failure).lower(), input='y\n')
                self.assertEqual(result.returncode, 1 if failure else 0, result.stdout + result.stderr)
                self.assertEqual(log.read_text().splitlines() if log.exists() else [], expected)



if __name__ == '__main__':
    unittest.main()
