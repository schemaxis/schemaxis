"""Hostile-evidence and lifecycle checks with a fake native executable: the strict TSV reader, text agreement, tampering, offline verification."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.tesseract import adaptor, tsv
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'examples/schemaxis/fixtures/tesseract/baseline.png'
FAKE = '''#!/usr/bin/env python3
import os, struct, sys, time
here = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(here, 'mode.txt')).read().strip()
if '--version' in sys.argv:
    print('tesseract 5.5.3'); print(' leptonica-1.87.0'); sys.exit(0)
if mode == 'sleep':
    open(os.path.join(here, 'child.pid'), 'w').write(str(os.getpid())); time.sleep(120)
image = open(sys.argv[1], 'rb').read(); width, height = struct.unpack('>II', image[16:24])
base = sys.argv[2]
head = 'level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext\\n'
rows = ['1\\t1\\t0\\t0\\t0\\t0\\t0\\t0\\t%d\\t%d\\t-1\\t' % (width, height)]
text = ''
if mode != 'empty':
    rows += ['2\\t1\\t1\\t0\\t0\\t0\\t45\\t50\\t388\\t43\\t-1\\t', '3\\t1\\t1\\t1\\t0\\t0\\t45\\t50\\t388\\t43\\t-1\\t', '4\\t1\\t1\\t1\\t1\\t0\\t45\\t50\\t388\\t43\\t-1\\t',
             '5\\t1\\t1\\t1\\t1\\t1\\t45\\t50\\t210\\t43\\t96.133446\\tNORTH', '5\\t1\\t1\\t1\\t1\\t2\\t283\\t50\\t150\\t43\\t95.335594\\t4096']
    text = 'NORTH 4096\\n\\n'
if mode == 'drift': text = 'NORTH 4097\\n\\n'
if mode == 'noreport': sys.exit(0)
open(base + '.tsv', 'w').write(head + '\\n'.join(rows) + '\\n'); open(base + '.txt', 'w').write(text)
'''
SHA = '0' * 64


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree, self.temp, True)
        self.exe = self.temp / 'fake-tesseract';self.exe.write_text(FAKE);self.exe.chmod(0o755);self.mode('ok')
        self.model = self.temp / 'eng.traineddata';self.model.write_bytes(b'model-bytes' * 100)
        self.image = self.temp / 'page.png';shutil.copy(BASELINE, self.image)
        self.document = {'version': 'schemaxis.tesseract/1', 'operation': 'recognizePage', 'image': {'path': str(self.image)},
                         'model': {'path': str(self.model), 'sha256': hashlib.sha256(self.model.read_bytes()).hexdigest()}, 'dpi': 200}

    def mode(self, value): (self.temp / 'mode.txt').write_text(value)

    def run_it(self, name='run', document=None, **kw):
        return adaptor.run(document or self.document, self.temp / name, executable=str(self.exe), **kw)

    def refuse(self, action, code):
        with self.assertRaises(SchemaxisError) as raised: action()
        self.assertEqual(raised.exception.fault.code, code, raised.exception.fault.to_dict())
        return raised.exception.fault


class Boundary(Fixture):
    def test_successful_fake_run_verifies_and_publishes_exact_members(self):
        result = self.run_it();directory = self.temp / 'run'
        self.assertTrue(result['verified']);self.assertEqual((result['words'], result['lines'], result['originState']), (2, 1, 'unknown'))
        self.assertEqual((directory / 'page.txt').read_text(), 'NORTH 4096\n')
        words = json.loads((directory / 'words.json').read_text())
        self.assertEqual(words['words'][0]['box'], {'left': 45, 'top': 50, 'width': 210, 'height': 43})
        self.assertEqual(words['words'][0]['confidence'], 96.133446)
        summary = json.loads((directory / 'ocr-summary.json').read_text())
        self.assertEqual((summary['status'], summary['review']['ocrTruthCertified'], summary['review']['confidenceCalibrated']), ('machine-draft', False, False))
        self.assertEqual(summary['origin']['state'], 'unknown');self.assertEqual(summary['settings']['psm'], 6)
        command = json.loads((directory / 'recognize-submission.json').read_text())['nativeCommand']
        self.assertEqual(command[0], __import__('sys').executable)
        self.assertIn("'--oem', '1', '--psm', '6', '--dpi', '200', '-c', 'tessedit_create_txt=1', '-c', 'tessedit_create_tsv=1'", (directory / 'recognize-launcher.py').read_text())
        self.assertEqual(adaptor.verify(directory), {k: v for k, v in json.loads((directory / 'result.json').read_text()).items() if k != 'status'})

    def test_offline_verification_never_launches_the_native_executable(self):
        self.run_it();self.exe.unlink()
        self.assertTrue(adaptor.verify(self.temp / 'run')['verified'])

    def test_faults_are_distinct_and_failed_attempts_are_retained(self):
        self.refuse(lambda: self.run_it('absent', {**self.document, 'image': {'path': str(self.temp / 'none.png')}}), 'INVALID_IMAGE_SOURCE')
        self.assertEqual(json.loads((self.temp / 'absent/result.json').read_text())['status'], 'failed')
        self.refuse(lambda: self.run_it('nomodel', {**self.document, 'model': {**self.document['model'], 'path': str(self.temp / 'none.traineddata')}}), 'INVALID_MODEL')
        self.refuse(lambda: self.run_it('badhash', {**self.document, 'model': {**self.document['model'], 'sha256': SHA}}), 'MODEL_HASH_MISMATCH')
        self.refuse(lambda: self.run_it('imghash', {**self.document, 'image': {'path': str(self.image), 'sha256': SHA}}), 'IMAGE_HASH_MISMATCH')
        self.refuse(lambda: adaptor.run(self.document, self.temp / 'noexe', executable='/nonexistent/tesseract'), 'INTERPRETER_NOT_FOUND')
        self.assertFalse((self.temp / 'noexe').exists())
        alpha = self.temp / 'alpha.png';alpha.write_bytes(__import__('tests.unit.test_tesseract', fromlist=['header']).header(10, 10, colour=6))
        self.refuse(lambda: self.run_it('alpha', {**self.document, 'image': {'path': str(alpha)}}), 'UNSUPPORTED_IMAGE')
        self.refuse(lambda: self.run_it('absent'), 'OUTPUT_EXISTS')
        link = self.temp / 'link.png';link.symlink_to(self.image)
        self.refuse(lambda: self.run_it('symlink', {**self.document, 'image': {'path': str(link)}}), 'INVALID_IMAGE_SOURCE')
        wrong = self.temp / 'wrong-runtime';wrong.write_text(FAKE.replace('5.5.3', '5.3.0'));wrong.chmod(0o755)
        self.refuse(lambda: adaptor.run(self.document, self.temp / 'oldrt', executable=str(wrong)), 'UNSUPPORTED_NATIVE_VERSION')

    def test_no_text_and_missing_output_and_drift_are_refused_not_published(self):
        self.mode('empty');self.refuse(lambda: self.run_it('empty'), 'OCR_NO_TEXT')
        self.assertFalse((self.temp / 'empty/page.txt').exists())
        self.mode('noreport');self.refuse(lambda: self.run_it('missing'), 'OCR_OUTPUT_MISSING')
        self.mode('drift');self.refuse(lambda: self.run_it('drift'), 'OCR_OUTPUT_INVALID')

    def test_timeout_terminates_the_native_process_tree(self):
        self.mode('sleep')
        self.refuse(lambda: self.run_it('slow', timeout=2), 'RUNNER_TIMED_OUT')
        pid = int((self.temp / 'child.pid').read_text())
        import os, time
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_cancellation_before_launch(self):
        with patch.object(adaptor, 'cancellation_requested', return_value=True):
            self.refuse(lambda: self.run_it('cancelled'), 'RUNNER_CANCELLED')
        self.assertEqual(json.loads((self.temp / 'cancelled/result.json').read_text())['status'], 'failed')


class Tamper(Fixture):
    def setUp(self):
        super().setUp();self.run_it();self.directory = self.temp / 'run'
        self.saved = {p: p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}

    def restore(self):
        for path in list(self.directory.rglob('*')):
            if path.is_symlink() or (path.is_file() and path not in self.saved): path.unlink()
        for path, data in self.saved.items():
            path.parent.mkdir(exist_ok=True);path.write_bytes(data)

    def refresh(self):
        """Recompute receipt digests so only semantic checks can catch the change."""
        receipt = json.loads((self.directory / 'verification.json').read_text());p = adaptor.plan(json.loads((self.directory / 'authored.json').read_text()))
        receipt['evidence'] = {n: adaptor.digest(self.directory, n, adaptor.evidence_limit(n)) for n in receipt['evidence']}
        receipt['artifacts'] = adaptor.artifacts(self.directory);atomic_json(self.directory / 'verification.json', receipt)

    def expect_failure(self, mutate, refreshed=True):
        mutate()
        if refreshed: self.refresh()
        self.refuse(lambda: adaptor.verify(self.directory), 'VERIFICATION_FAILED')
        self.restore();self.assertTrue(adaptor.verify(self.directory)['verified'])

    def edit_json(self, name, change):
        data = json.loads((self.directory / name).read_text());change(data);atomic_json(self.directory / name, data)

    def test_published_files_cannot_be_forged_even_with_refreshed_digests(self):
        self.expect_failure(lambda: self.edit_json('words.json', lambda d: d['words'][0]['box'].update(left=46)))
        self.expect_failure(lambda: self.edit_json('words.json', lambda d: d['words'][0].update(confidence=99.5)))
        self.expect_failure(lambda: self.edit_json('words.json', lambda d: d['words'][0].update(text='SOUTH')))
        self.expect_failure(lambda: (self.directory / 'page.txt').write_text('FORGED\n'))
        self.expect_failure(lambda: self.edit_json('ocr-summary.json', lambda d: d['review'].update(ocrTruthCertified=True)))
        self.expect_failure(lambda: self.edit_json('ocr-summary.json', lambda d: d['origin'].update(state='declared-bound-to-pixels')))

    def test_native_tsv_and_text_tampering(self):
        tsv_path = self.directory / 'native.tsv'
        original = tsv_path.read_text()
        self.expect_failure(lambda: tsv_path.write_text(original.replace('level\t', 'Level\t', 1)))
        self.expect_failure(lambda: tsv_path.write_text(original + '5\t1\t1\t1\t1\t3\t300\t50\t10\t10\t90\tEXTRA\n'))
        self.expect_failure(lambda: tsv_path.write_text(original.replace('96.133446', '196.1')))
        self.expect_failure(lambda: tsv_path.write_text(original.replace('\t210\t43\t', '\t999\t43\t')))
        self.expect_failure(lambda: tsv_path.write_text(original.replace('NORTH', 'SOUTH')))
        self.expect_failure(lambda: (self.directory / 'native.txt').write_text('NORTH 4097\n'))
        self.expect_failure(lambda: tsv_path.unlink(), refreshed=False)
        self.expect_failure(lambda: (self.directory / 'native.txt').unlink(), refreshed=False)

    def test_stale_source_model_runtime_and_command_bindings(self):
        shutil.copy(ROOT / 'examples/schemaxis/fixtures/tesseract/changed.png', self.directory / 'captured-page.png')
        self.refuse(lambda: adaptor.verify(self.directory), 'VERIFICATION_FAILED');self.restore()
        (self.directory / 'tessdata/eng.traineddata').write_bytes(b'other model')
        self.refuse(lambda: adaptor.verify(self.directory), 'VERIFICATION_FAILED');self.restore()
        self.expect_failure(lambda: self.edit_json('runtime.json', lambda d: d.update(executable='/forged/tesseract')))
        self.expect_failure(lambda: self.edit_json('runtime.json', lambda d: d['files'][0].update(sha256='f' * 64)), refreshed=False)
        self.expect_failure(lambda: self.edit_json('verification.json', lambda d: d.update(runtime='tesseract 6.0.0')), refreshed=False)
        launcher = self.directory / 'recognize-launcher.py'
        self.expect_failure(lambda: launcher.write_text(launcher.read_text().replace("'--psm', '6'", "'--psm', '7'")))
        self.expect_failure(lambda: self.edit_json('recognize-submission.json', lambda d: d.update(exitCode=1)))
        self.expect_failure(lambda: self.edit_json('recognize-inputs.json', lambda d: d['files'].update({'captured-page.png': 'e' * 64})))
        self.expect_failure(lambda: self.edit_json('authored.json', lambda d: d.update(dpi=300)), refreshed=False)

    def test_membership_and_filenames(self):
        self.expect_failure(lambda: (self.directory / 'extra.txt').write_text('x'), refreshed=False)
        self.expect_failure(lambda: (self.directory / 'tessdata/other.traineddata').write_bytes(b'x'), refreshed=False)
        self.expect_failure(lambda: (self.directory / 'page.txt').unlink(), refreshed=False)
        link = self.directory / 'words.json'
        def swap():
            data = link.read_bytes();link.unlink();(self.temp / 'elsewhere.json').write_bytes(data);link.symlink_to(self.temp / 'elsewhere.json')
        self.expect_failure(swap, refreshed=False)
        self.edit_json('result.json', lambda d: d.update(verified=False, status='failed'))
        self.refuse(lambda: adaptor.verify(self.directory), 'INCOMPLETE_EXECUTION');self.restore()
        self.edit_json('result.json', lambda d: d.update(words=3))
        self.refuse(lambda: adaptor.verify(self.directory), 'VERIFICATION_FAILED');self.restore()


class StrictTsv(unittest.TestCase):
    HEAD = '\t'.join(tsv.HEADER) + '\n'
    PAGE = '1\t1\t0\t0\t0\t0\t0\t0\t100\t50\t-1\t\n'
    TREE = ['2\t1\t1\t0\t0\t0\t10\t10\t80\t30\t-1\t', '3\t1\t1\t1\t0\t0\t10\t10\t80\t30\t-1\t', '4\t1\t1\t1\t1\t0\t10\t10\t80\t30\t-1\t']
    WORD = '5\t1\t1\t1\t1\t1\t10\t10\t40\t20\t88.5\tWORD'

    def build(self, *rows, head=None, page=None): return ((head or self.HEAD) + (page or self.PAGE) + ''.join(r + '\n' for r in rows)).encode()

    def bad(self, data):
        with self.assertRaises(SchemaxisError) as raised: tsv.parse(data, 100, 50)
        self.assertEqual(raised.exception.fault.code, 'OCR_OUTPUT_INVALID', raised.exception.fault.to_dict())

    def test_valid_and_hierarchy_counts(self):
        parsed = tsv.parse(self.build(*self.TREE, self.WORD, self.WORD.replace('\t1\t10\t10\t40', '\t2\t55\t10\t30').replace('WORD', 'TWO')), 100, 50)
        self.assertEqual((parsed['lines'], parsed['blocks'], parsed['paragraphs']), (['WORD TWO'], 1, 1))
        self.assertEqual(tsv.agree(parsed, b'WORD  TWO\n\n'), 'WORD TWO\n')
        with self.assertRaises(SchemaxisError): tsv.agree(parsed, b'WORD\n')

    def test_each_structural_deviation_is_refused(self):
        w = self.WORD
        cases = [self.build(*self.TREE, w, head=self.HEAD.replace('conf', 'confidence')), self.build(*self.TREE, w, head=self.HEAD.rstrip('\n') + '\textra\n'),
                 self.build(*self.TREE, w, page='1\t1\t0\t0\t0\t0\t0\t0\t99\t50\t-1\t\n'), self.build(*self.TREE, w, page='1\t1\t0\t0\t0\t0\t1\t0\t100\t50\t-1\t\n'),
                 self.build(*self.TREE, w, page='1\t2\t0\t0\t0\t0\t0\t0\t100\t50\t-1\t\n'),
                 self.build(*self.TREE, w + '\textra'), self.build(*self.TREE, w.replace('88.5', '100.5')), self.build(*self.TREE, w.replace('88.5', '-1')),
                 self.build(*self.TREE, w.replace('88.5', '88.1234567')), self.build(*self.TREE, w.replace('88.5', 'nan')), self.build(*self.TREE, w.replace('88.5', '88.50e0')),
                 self.build(*self.TREE, w.replace('\t40\t20\t', '\t0\t20\t')), self.build(*self.TREE, w.replace('\t10\t10\t40', '\t70\t10\t40')),
                 self.build(*self.TREE, w.replace('WORD', '')), self.build(*self.TREE, w.replace('WORD', ' WORD')), self.build(*self.TREE, w.replace('WORD', 'WO RD')),
                 self.build(*self.TREE, w.replace('WORD', 'WO​RD')), self.build(*self.TREE, w.replace('1\t1\t1\t1\t1\t', '1\t1\t1\t1\t2\t', 1).replace('5\t1', '5\t1', 1)),
                 self.build(self.TREE[1], self.TREE[2], w), self.build(self.TREE[0], self.TREE[2], w), self.build(*self.TREE),
                 self.build(*self.TREE, w, self.TREE[0].replace('\t1\t1\t0', '\t1\t3\t0')), self.build(w), self.build(*self.TREE, '6\t1\t1\t1\t1\t1\t10\t10\t40\t20\t88.5\tWORD'),
                 self.build(*self.TREE, w).replace(b'\n', b'\r\n'), self.build(*self.TREE, w).rstrip(b'\n'), self.build(*self.TREE, w) + b'\n', self.build(*self.TREE, w).replace(b'WORD', b'\xff\xfe'),
                 b'\xef\xbb\xbf' + self.build(*self.TREE, w), (self.HEAD).encode(), b'', self.build(*self.TREE, w, w)]
        for index, data in enumerate(cases):
            with self.subTest(case=index): self.bad(data)

    def test_resource_limit_is_checked_without_giant_allocation(self):
        rows = [self.TREE[0], self.TREE[1], self.TREE[2]] + [self.WORD.replace('\t1\t10\t10\t40', '\t%d\t10\t10\t1' % (i + 1)) for i in range(tsv.MAX_WORDS + 1)]
        with self.assertRaises(SchemaxisError) as raised: tsv.parse(self.build(*rows), 100, 50)
        self.assertEqual(raised.exception.fault.code, 'OCR_RESOURCE_LIMIT')

    def test_text_policy_rejects_control_characters(self):
        for data in (b'a\tb\n', b'a\r\n', b'a\x0c', b'\xef\xbb\xbfa\n', b'\xff'):
            with self.assertRaises(SchemaxisError): tsv.native_lines(data)
