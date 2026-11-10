"""Shared fixtures and a native case base of the E4 copy, sidecar and naming tests (standard library only; every fixture is hand-built from raw TIFF, XMP and IIM entries).

Expectations in the E4 tests are hand-written literals taken from the contract tables, never computed by the code under test or by ExifTool.
"""
import contextlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'tests/unit')]

import author_exiftool_fixtures as a  # noqa: E402
import exiftool_e3_fixtures as fx  # noqa: E402
from schemaxis import publication_metadata  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

V = 'schemaxis.exiftool/1'
O = 'II'
RESULTS = {}


def rational(tag, n, d):
    return a.rational_entry(O, tag, (n, d))


def srational(tag, n, d):
    return a.srational_entry(O, tag, (n, d))


def lang_alt(prop, default, **others):
    items = '<rdf:li xml:lang="x-default">%s</rdf:li>' % default + ''.join('<rdf:li xml:lang="%s">%s</rdf:li>' % (k.replace('_', '-'), v) for k, v in others.items())
    return '<%s><rdf:Alt>%s</rdf:Alt></%s>' % (prop, items, prop)


def bag(prop, *items, kind='Bag'):
    return '<%s><rdf:%s>%s</rdf:%s></%s>' % (prop, kind, ''.join('<rdf:li>%s</rdf:li>' % i for i in items), kind, prop)


def master(seed=1, **extra):
    """The rich source photo of the transfer tests: bilingual title, two keywords, two creators, copyright, camera, lens, serial and exact exposure pairs."""
    xmp = fx.xmp_properties(extra=lang_alt('dc:title', 'Harbour', de_DE='Hafen') + bag('dc:subject', 'k1', 'k2') + bag('dc:creator', 'Ann; Bob', 'Cy', kind='Seq')
                            + lang_alt('dc:rights', '(c) 2024 A') + '<xmp:Rating>4</xmp:Rating>')
    exif_extra = [rational(0x829A, 10, 30), rational(0x829D, 28, 10), a.short_entry(O, 0x8827, 400), rational(0x920A, 35, 2), a.short_entry(O, 0xA405, 52), srational(0x9204, -2, 6),
                  a.ascii_entry(0xA433, 'LensCo'), a.ascii_entry(0xA434, 'L50'), a.ascii_entry(0xA435, 'L456')]
    return fx.jpeg(make='Canon', model='EOS 5D', serial='B123', xmp=xmp, exif_extra=exif_extra, seed=seed, **extra)


def plain(seed=2, **extra):
    return fx.jpeg(make='Other', model='Old', seed=seed, **extra)


class NativeCase(unittest.TestCase):
    """A fresh private directory per test and the real ExifTool 13.55 named by SCHEMAXIS_EXIFTOOL (skipped otherwise)."""

    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='e4-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.media = self.tmp / 'in'
        self.media.mkdir()

    def put(self, name, data):
        (self.media / name).write_bytes(data)
        return str(self.media / name)

    def items(self, *names):
        return {'items': [{'id': n, 'path': str(self.media / (n + '.jpg'))} for n in names]}

    def run_op(self, document, name):
        return adaptor.run(document, self.tmp / name, executable=self.exe)

    def refuses(self, document, name, code):
        with self.assertRaises(SchemaxisError) as caught:
            self.run_op(document, name)
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def verify(self, name):
        return adaptor.verify(self.tmp / name, executable=self.exe)

    def read(self, name, relative):
        return (self.tmp / name / relative).read_bytes()

    def json(self, name, relative):
        return json.loads(self.read(name, relative))

    def record(self, case, operation, kind='control', **more):
        RESULTS[case] = {'id': case, 'operation': operation, 'container': 'jpeg', 'kind': kind, **more}


def snapshot(data, groups=None, fields=None):
    """The typed snapshot of a JPEG's bytes through the shipped readers (used only to read OUTPUT facts back; expectations stay hand-written literals)."""
    from schemaxis.adaptors.exiftool import containers, e4model, records
    return e4model.snapshot(records.Payloads(containers.locate(data)), e4model.selection({'groups': groups or [], 'fields': fields or []}))


def mutate_and_refresh(case, source, label, change, expected_code, during=None):
    """A metadata-first mutant: copy a retained run, apply ``change``, refresh every ordinary binding so ``publication_metadata.verify`` PASSES, then require one exact refusal."""
    target = case.tmp / ('mf-' + label)
    shutil.copytree(case.tmp / source, target, symlinks=True)
    change(target)
    refresh(target, case.tmp / source)
    assert publication_metadata.verify(target)['verified'], 'the publication metadata must verify before the public route is asked'
    with contextlib.ExitStack() as stack:
        if during is not None:                  # a reader mutant: patched while the public verification runs
            stack.enter_context(during())
        with case.assertRaises(SchemaxisError) as caught:
            adaptor.verify(target, executable=case.exe)
    fault = caught.exception.fault
    observed = fault.to_dict().get('observed', {})
    cause = observed.get('cause', {}) if isinstance(observed, dict) else {}
    code, location = cause.get('code', fault.code), cause.get('location', fault.location)
    message = cause.get('message') or fault.message
    case.assertEqual(code, expected_code, (code, location, message))
    case.assertTrue(isinstance(message, str) and message.strip())
    RESULTS['mf:' + label] = {'id': 'mf:' + label, 'operation': json.loads((target / 'authored.json').read_text())['operation'], 'container': 'jpeg', 'publicationMetadataVerified': True,
                              'code': code, 'location': location, 'message': message, 'route': 'public adaptor.verify after the full refresh', 'independentlyVerified': True}
    return (code, location) if during is None else (code, location, message)


def refresh(directory, old):
    """Refresh every ordinary mutable binding of a copied E4 run (stage input digests, receipt evidence and artifact records, publication metadata)."""
    from schemaxis.adaptors.exiftool import e4host, editing
    directory = Path(directory)
    host = json.loads((directory / 'authored.json').read_text())['operation'] in e4host.OPERATIONS
    for path in sorted(directory.glob('*-submission.json')):
        path.write_text(path.read_text().replace(str(old), str(directory)))
    for path in sorted(directory.glob('*-inputs.json')):
        data = json.loads(path.read_text())
        mapper = (lambda n: e4host.stage_path_of(directory, n) if n.startswith('stage/') else n) if host else (lambda n: editing.stage_path_of(directory, n) if n.startswith('stage/') else n)
        limit = e4host.limit_of if host else editing.limit_of
        atomic_json(path, {'files': {n: limit_digest(directory, mapper(n), limit) for n in data['files']}})
    receipt = json.loads((directory / 'verification.json').read_text())
    limit = e4host.limit_of if host else editing.limit_of
    receipt['evidence'] = {n: limit_digest(directory, e4host.stage_path_of(directory, n) if host and n.startswith('stage/') else editing.stage_path_of(directory, n) if n.startswith('stage/') else n, limit) for n in receipt['evidence']}
    for entry in receipt['artifacts']:
        relative = str(Path(entry['file']).relative_to(old))
        entry['file'] = str(directory / relative)
        entry['sha256'] = limit_digest(directory, relative, limit)
    atomic_json(directory / 'verification.json', receipt)
    publication_metadata.finalise(directory)


def limit_digest(directory, name, limit):
    return adaptor.sha(adaptor.bounded(directory / name, limit=limit(name)))
