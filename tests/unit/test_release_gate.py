"""Release gate pattern matching, private patterns, allowlists, directory and package scans."""
import base64
import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import release_gate as gate

HOME = '/' + 'home' + '/'
SECRET = 'acme-internal'      # invented private substring
CODENAME = 'ZEPHYR'           # invented private whole word
DOTTED = 'acme' + '.widgets'  # invented private dotted name


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gate.main(argv)
    return code, out.getvalue().splitlines()


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp)
        self.private = self.temp / 'private.json'
        self.private.write_text(json.dumps({
            'substrings': [SECRET, DOTTED], 'words': [CODENAME],
            'regex': [{'name': 'quoted-id', 'pattern': r'"widgets"'}]}))
        self.addCleanup(gate.configure)
        gate.configure()

    def test_builtin_patterns_are_project_neutral(self):
        self.assertEqual(gate.match_line('see ' + HOME.upper() + 'user'), [HOME])
        self.assertEqual(gate.match_line('/' + 'Users/someone/x'), ['/' + 'Users/'])
        self.assertEqual(gate.match_line('key AKIA' + 'ABCDEFGHIJKLMNOP'), ['aws-access-key-id'])
        self.assertEqual(gate.match_line(SECRET + ' ' + CODENAME), [])

    def test_private_patterns(self):
        gate.configure([self.private])
        self.assertEqual(gate.match_line('an ' + SECRET.upper() + ' note'), [SECRET])
        self.assertEqual(gate.match_line('the ' + CODENAME + ' adaptor'), [CODENAME])
        self.assertEqual(gate.match_line('(' + CODENAME + ')'), [CODENAME])
        self.assertEqual(gate.match_line('a zephyr breeze'), [])
        self.assertEqual(gate.match_line(CODENAME + 'X'), [])
        self.assertEqual(gate.match_line('ids: ["widgets"]'), ['quoted-id'])
        self.assertEqual(gate.match_line('acmeXwidgets'), [])

    def test_private_patterns_from_environment(self):
        tree = self.temp / 'tree'
        tree.mkdir()
        (tree / 'a.md').write_text('uses ' + CODENAME + '\n')
        self.assertEqual(run(['--no-git', '--no-allow', '--path', str(tree)]), (0, []))
        with mock.patch.dict(os.environ, {'SCHEMAXIS_RELEASE_PATTERNS': str(self.private)}):
            code, lines = run(['--no-git', '--no-allow', '--path', str(tree)])
        self.assertEqual((code, lines), (1, [f'{tree.as_posix()}/a.md:1: {CODENAME}']))

    def test_invalid_private_patterns_are_input_errors(self):
        bad = self.temp / 'bad.json'
        bad.write_text(json.dumps({'words': ['']}))
        self.assertEqual(run(['--no-git', '--patterns', str(bad)])[0], 2)

    def test_file_names_are_reported_as_line_zero(self):
        gate.configure([self.private])
        self.assertEqual(gate.scan_text('examples/' + SECRET + '/a.md', 'clean'),
                         [('examples/' + SECRET + '/a.md', 0, SECRET)])

    def test_binary_content_is_skipped_but_name_checked(self):
        gate.configure([self.private])
        hits = gate.scan_bytes('x/' + SECRET + '.bin', b'\0' + HOME.encode())
        self.assertEqual(hits, [('x/' + SECRET + '.bin', 0, SECRET)])
        self.assertEqual(gate.scan_bytes('t.txt', HOME.encode()), [('t.txt', 1, HOME)])

    def test_gzip_fields_are_scanned_as_their_decoded_text(self):
        gate.configure([self.private])
        body = 'clean line\nmentions ' + CODENAME + ' here\n' + 'filler text\n' * 200
        encoded = base64.b64encode(gzip.compress(body.encode(), mtime=0)).decode()
        page = '{"id":"x","bodyGzip":"' + encoded + '"}\n'
        self.assertEqual(gate.scan_text('help/x.json', page), [('help/x.json!bodyGzip', 2, CODENAME)])
        # A run of letters inside the encoding is not a hit: the encoding is not scanned.
        chance = encoded[40:44]
        self.assertNotIn(chance, body)
        noise = self.temp / 'noise.json'
        noise.write_text(json.dumps({'substrings': [chance]}))
        gate.configure([noise])
        self.assertEqual(gate.scan_text('help/x.json', page), [])
        # A field that is not gzip is scanned as written.
        gate.configure([self.private])
        plain = '{"bodyGzip":"' + base64.b64encode(('see ' + SECRET).encode()).decode() + '"}'
        self.assertEqual(gate.scan_text('help/y.json', plain), [])
        self.assertEqual(gate.scan_text('help/y.json', '{"bodyGzip":"' + SECRET + '"}'),
                         [('help/y.json', 1, SECRET)])

    def test_allowlist_glob_and_pattern_restriction(self):
        allow = self.temp / 'allow.json'
        allow.write_text(json.dumps({'allow': [
            {'glob': 'docs/*.md', 'reason': 'test', 'patterns': [CODENAME]},
            {'glob': 'pkg.whl', 'reason': 'archive member path', 'patterns': [SECRET]},
            {'glob': 'inner/*', 'reason': 'member path match'}]}))
        entries = gate.load_allow(allow)
        self.assertTrue(gate.allowed(('docs/a.md', 3, CODENAME), entries))
        self.assertFalse(gate.allowed(('docs/a.md', 3, HOME), entries))
        self.assertFalse(gate.allowed(('src/a.md', 3, CODENAME), entries))
        self.assertTrue(gate.allowed(('pkg.whl!inner/x.py', 1, HOME), entries))

    def test_allowlist_requires_reason(self):
        allow = self.temp / 'allow.json'
        allow.write_text(json.dumps({'allow': [{'glob': '*'}]}))
        with self.assertRaises(ValueError):
            gate.load_allow(allow)

    def test_directory_scan_and_exit_codes(self):
        tree = self.temp / 'tree'
        (tree / 'sub').mkdir(parents=True)
        (tree / 'sub' / 'notes.md').write_text('line\nuse ' + HOME + 'me\n')
        (tree / 'clean.txt').write_text('nothing here\n')
        code, lines = run(['--no-git', '--no-allow', '--path', str(tree)])
        self.assertEqual(code, 1)
        self.assertEqual(lines, [f'{tree.as_posix()}/sub/notes.md:2: {HOME}'])
        allow = self.temp / 'allow.json'
        allow.write_text(json.dumps({'allow': [{'glob': '*/sub/*', 'reason': 'test'}]}))
        self.assertEqual(run(['--no-git', '--allow', str(allow), '--path', str(tree)]), (0, []))
        (tree / 'sub' / 'notes.md').write_text('clean\n')
        self.assertEqual(run(['--no-git', '--no-allow', '--path', str(tree)]), (0, []))

    def test_wheel_and_zip_members(self):
        wheel = self.temp / 'pkg-1.0-py3-none-any.whl'
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('pkg/a.py', 'x = 1\ny = "' + CODENAME + '"\n')
            archive.writestr('pkg/' + SECRET + '.txt', 'fine')
        code, lines = run(['--no-git', '--no-allow', '--patterns', str(self.private),
                           '--path', str(wheel)])
        self.assertEqual(code, 1)
        self.assertEqual(lines, [f'{wheel.as_posix()}!pkg/a.py:2: {CODENAME}',
                                 f'{wheel.as_posix()}!pkg/' + SECRET + '.txt:0: ' + SECRET])

    def test_tar_gz_members(self):
        gate.configure([self.private])
        sdist = self.temp / 'pkg-1.0.tar.gz'
        data = ('see ' + DOTTED + '/1\n').encode()
        with tarfile.open(sdist, 'w:gz') as archive:
            info = tarfile.TarInfo('pkg-1.0/README.md')
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        hits = gate.scan_location(str(sdist))
        self.assertEqual(hits, [(f'{sdist.as_posix()}!pkg-1.0/README.md', 1, DOTTED)])

    def test_missing_path_is_an_input_error(self):
        self.assertEqual(run(['--no-git', '--path', str(self.temp / 'absent')])[0], 2)

    @unittest.skipUnless(shutil.which('git'), 'git is not installed')
    def test_tracked_files_only(self):
        repo = self.temp / 'repo'
        (repo / 'tools').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'tracked.txt').write_text(HOME + '\n')
        (repo / 'untracked.txt').write_text(HOME + '\n')
        (repo / 'tools' / 'release_gate_allow.json').write_text(json.dumps({'allow': []}))
        subprocess.run(['git', 'add', 'tracked.txt', 'tools'], cwd=repo, check=True)
        self.assertEqual(run(['--repo', str(repo)]), (1, ['tracked.txt:1: ' + HOME]))

    def test_repository_allowlist_is_valid(self):
        entries = gate.load_allow(gate.DEFAULT_ALLOW)
        self.assertTrue(entries)


if __name__ == '__main__':
    unittest.main()
