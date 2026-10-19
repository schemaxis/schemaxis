#!/usr/bin/env python3
"""Native QPDF qualification: literal oracle, replaced-publication tamper matrix, negatives, runtimes, lifecycle and shared boundaries.

Every verification here goes through the public standalone route (registry.verify with stored configuration) unless a
boundary check says otherwise. Hostile cases replace the actual published PDF and refresh the receipt's digests and the
publication companions; none of them is judged by its hashes. Expected values are literal constants, never producer output.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

from schemaxis import workflow
from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors import registry
from schemaxis.adaptors.qpdf import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation, execution_deadline
from schemaxis.publication_metadata import finalise
import qualify_qpdf_fixtures as literal

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/qpdf'
PHASES = ('kit', 'tamper', 'negatives', 'runtime', 'lifecycle', 'boundaries')
sha = lambda data: hashlib.sha256(data).hexdigest()


LAST_FAULT = {}


def outcome(action):
    """Return ('ok', result) or ('fault', code) for a SchemaxisError; anything else is a qualification failure."""
    try:
        return 'ok', action()
    except SchemaxisError as error:
        LAST_FAULT.update(message=error.fault.message, location=error.fault.location)
        return 'fault', error.fault.code


def refused(action, codes, label=''):
    kind, value = outcome(action)
    assert kind == 'fault' and value in codes, '%s: expected %s, observed %s %s' % (label, sorted(codes), kind, value)
    return value


def authored(sources, pages):
    return {'version': adaptor.VERSION, 'operation': 'assemble', 'sources': [{'name': n, 'path': str(p)} for n, p in sources.items()],
            'pages': [{'source': s, 'page': p, **({'rotate': r} if r else {})} for s, p, r in pages]}


class Qualification:
    def __init__(self, directory, qpdf, mupdf):
        self.directory, self.qpdf, self.mupdf = directory, str(qpdf), str(mupdf)
        self.locations = {'qpdf': self.qpdf, 'mupdf': self.mupdf}
        self.sources = {'cover': FIXTURES / 'cover.pdf', 'report': FIXTURES / 'report.pdf'}
        self.report = {}
        (directory / 'tmp').mkdir()
        tempfile.tempdir = str(directory / 'tmp')              # scratch directories stay inside the evidence folder
        os.environ['TMPDIR'] = str(directory / 'tmp')
        self.configure(self.locations)

    # -------------------------------------------------------------- configuration and helpers
    def configure(self, locations, name='config.json'):
        """Stored configuration for the standalone verify route; the environment fallbacks are cleared."""
        path = self.directory / name
        atomic_json(path, {'version': 1, 'locations': locations})
        os.environ['SCHEMAXIS_CONFIG'] = str(path)
        os.environ.pop('SCHEMAXIS_QPDF', None)
        os.environ.pop('SCHEMAXIS_MUPDF', None)

    def clone(self, source, target):
        """Copy a run directory next to the original (its schema snapshot root is '..'). The receipt names publications by absolute path, so the copy's paths are rebuilt to point inside the copy."""
        shutil.copytree(source, target)
        receipt = json.loads((target / 'verification.json').read_text())
        for artifact in receipt['artifacts']:
            artifact['file'] = str(target.resolve() / Path(artifact['file']).name)
        atomic_json(target / 'verification.json', receipt)

    def fake(self, name, body):
        path = self.directory / 'fakes' / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o755)
        return str(path)

    def run(self, document, name, **options):
        return registry.run(document, self.directory / name, locations=options.pop('locations', self.locations), timeout=options.pop('timeout', 120))

    def verified(self, name):
        result = registry.verify(self.directory / name)
        assert result['verified'] is True and result['runtime'] == 'qpdf version 12.4.2; mutool version 1.28.5', result
        return result

    def literal(self, pdf, expectations):
        scratch = self.directory / 'literal'
        scratch.mkdir(exist_ok=True)
        return literal.check(self.mupdf, pdf, expectations, scratch)

    def published(self, workflow_directory, operation, name):
        """Latest scheduled attempt's file: workflows publish under <operation>/batch-N/attempt-NNNN/."""
        found = sorted((self.directory / workflow_directory / operation).glob('batch-0/attempt-*/' + name))
        assert found, (workflow_directory, operation, name)
        return found[-1]

    def qpdf_json(self, pdf):
        data = subprocess.run([self.qpdf, '--json', '--json-key=qpdf', '--json-key=pages', str(pdf)], check=True, capture_output=True, timeout=60).stdout
        return json.loads(data)

    # -------------------------------------------------------------- phase: shared kit and literal oracle
    def kit(self):
        receipt = qualify(adaptor.VERSION, self.directory / 'kit', native=True, root=ROOT, locations=self.locations, timeout=120, wall_timeout=900)
        expectations = {
            'ordered-assembly': [('cover', 1, 0), ('report', 2, 0), ('report', 1, 0), ('report', 3, 0), ('report', 3, 90)],
            'reversed-rotated': [('report', 4, 90), ('report', 3, 180), ('report', 3, 270), ('cover', 1, 90)]}
        independent = {case: self.literal(self.directory / 'kit' / case / 'assembled.pdf', expected) for case, expected in expectations.items()}
        self.report['kit'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtime': [c['runtime'] for c in receipt['cases']],
                              'lifecycle': receipt['lifecycle'], 'integrityChecks': {c['id']: len(c['integrity']) for c in receipt['cases']},
                              'literalOracle': {case: len(pages) for case, pages in independent.items()}}

    # -------------------------------------------------------------- phase: replaced-publication tamper matrix
    def tamper(self):
        base_sources = {'crop': self.directory / 'tamper-sources/crop-a.pdf', 'twin': self.directory / 'tamper-sources/twin-red.pdf',
                        'mark': self.directory / 'tamper-sources/mark-a.pdf', 'digit': self.directory / 'tamper-sources/digit-0.pdf'}
        alternates = {'crop': literal.cropvar([0, 0, 200, 299]), 'twin': literal.twin(b'0 0.7 0'), 'mark': literal.mark(160), 'digit': literal.digit(8)}
        (self.directory / 'tamper-sources').mkdir()
        base_bytes = {'crop': literal.cropvar([0, 0, 200, 300]), 'twin': literal.twin(b'1 0 0'), 'mark': literal.mark(150), 'digit': literal.digit(0)}
        for name, path in base_sources.items():
            path.write_bytes(base_bytes[name])
            (self.directory / 'tamper-sources' / (name + '-alt.pdf')).write_bytes(alternates[name])
        pages = [('crop', 1, 0), ('twin', 1, 0), ('mark', 1, 0), ('digit', 1, 0), ('twin', 1, 90), ('mark', 1, 180), ('crop', 1, 90)]
        self.run(authored(base_sources, pages), 'tamper-base')
        base = self.directory / 'tamper-base'
        real = (base / 'assembled.pdf').read_bytes()

        def assemble(sources, page_list, out):
            command = [self.qpdf, '--suppress-recovery', '--empty', '--pages']
            for name, page, _ in page_list:
                command += [str(sources[name]), str(page)]
            command += ['--'] + ['--rotate=+%d:%d' % (r, i) for i, (_, _, r) in enumerate(page_list, 1) if r]
            command += ['--remove-page-labels', '--deterministic-id', str(out)]
            subprocess.run(command, check=True, capture_output=True, timeout=60)
            return out.read_bytes()

        def replacement(label):
            out = self.directory / 'tamper-work' / (label + '.pdf')
            alt = lambda name: {**base_sources, name: self.directory / 'tamper-sources' / (name + '-alt.pdf')}
            if label == 'swap-two-pages':
                return assemble(base_sources, [pages[1], pages[0], *pages[2:]], out)
            if label == 'drop-last-page':
                return assemble(base_sources, pages[:-1], out)
            if label == 'extra-page':
                return assemble(base_sources, pages + [('digit', 1, 0)], out)
            if label == 'wrong-rotation-one-page':
                return assemble(base_sources, [pages[0], ('twin', 1, 180), *pages[2:]], out)
            if label == 'stale-box-source':
                return assemble(alt('crop'), pages, out)
            if label == 'different-resource-colour':
                return assemble(alt('twin'), pages, out)
            if label == 'near-identical-small-mark':
                return assemble(alt('mark'), pages, out)
            if label == 'one-digit-text-change':
                return assemble(alt('digit'), pages, out)
            if label == 'truncated-60-percent':
                return real[:int(len(real) * .6)]
            if label == 'zero-bytes':
                return b''
            if label == 'garbage':
                return b'%PDF-1.7\n' + os.urandom(2000)
            if label == 'encrypted-copy':
                subprocess.run([self.qpdf, '--encrypt', '', 'owner', '256', '--', str(base / 'assembled.pdf'), str(out)], check=True, capture_output=True, timeout=60)
                return out.read_bytes()
            if label in ('inject-page-aa', 'inject-catalogue-openaction'):
                parsed = self.qpdf_json(base / 'assembled.pdf')
                objects = parsed['qpdf'][1]
                target = 'obj:' + (parsed['pages'][0]['object'] if label == 'inject-page-aa' else objects['trailer']['value']['/Root'])
                extra = {'/AA': {'/O': {'/S': '/JavaScript', '/JS': 'u:1'}}} if label == 'inject-page-aa' else {'/OpenAction': {'/S': '/JavaScript', '/JS': 'u:1'}}
                update = {'qpdf': [{'jsonversion': 2, 'pushedinheritedpageresources': False, 'calledgetallpages': False}, {target: {'value': {**objects[target]['value'], **extra}}}]}
                path = self.directory / 'tamper-work' / (label + '.json')
                path.write_text(json.dumps(update))
                subprocess.run([self.qpdf, '--update-from-json=' + str(path), str(base / 'assembled.pdf'), str(out)], check=True, capture_output=True, timeout=60)
                return out.read_bytes()
            if label == 'EQUIVALENT-resave-with-object-streams':
                subprocess.run([self.qpdf, '--object-streams=generate', '--compress-streams=y', str(base / 'assembled.pdf'), str(out)], check=True, capture_output=True, timeout=60)
                return out.read_bytes()
            if label == 'EQUIVALENT-identical-bytes':
                return real
            raise AssertionError(label)

        (self.directory / 'tamper-work').mkdir()
        labels = ['swap-two-pages', 'drop-last-page', 'extra-page', 'wrong-rotation-one-page', 'stale-box-source', 'different-resource-colour',
                  'near-identical-small-mark', 'one-digit-text-change', 'truncated-60-percent', 'zero-bytes', 'garbage', 'encrypted-copy',
                  'inject-page-aa', 'inject-catalogue-openaction', 'EQUIVALENT-resave-with-object-streams', 'EQUIVALENT-identical-bytes']
        modes = ('hashes-refreshed', 'original-summary-kept', 'summary-forged-and-refreshed')
        rows = []
        for label in labels:
            data = replacement(label)
            for mode in modes:
                run = self.directory / ('tamper--%s--%s' % (label, mode))      # siblings of the base run: the schema snapshot root is '..'
                self.clone(base, run)
                (run / 'assembled.pdf').write_bytes(data)
                receipt = json.loads((run / 'verification.json').read_text())
                receipt['artifacts'][0]['sha256'] = sha(data)
                if mode == 'summary-forged-and-refreshed':
                    summary = json.loads((run / 'assembly-summary.json').read_text())
                    summary['pages'][0], summary['pages'][1] = summary['pages'][1], summary['pages'][0]       # a claim consistent with swapped pages
                    forged = adaptor.encode(summary)
                    (run / 'assembly-summary.json').write_bytes(forged)
                    receipt['artifacts'][1]['sha256'] = sha(forged)
                atomic_json(run / 'verification.json', receipt)
                finalise(run)                                       # publication companions describe the replaced bytes
                kind, value = outcome(lambda: registry.verify(run))
                equivalent = label.startswith('EQUIVALENT')
                if equivalent and mode == 'summary-forged-and-refreshed':
                    expected = ('fault', 'VERIFICATION_FAILED')    # equivalent bytes do not excuse a forged summary
                elif equivalent:
                    expected = ('ok', True)
                else:
                    expected = ('fault', 'VERIFICATION_FAILED')
                observed = (kind, value['verified'] if kind == 'ok' else value)
                assert observed == expected, '%s / %s: expected %s, observed %s' % (label, mode, expected, observed)
                rows.append({'tamper': label, 'mode': mode, 'observed': observed[1], **({'firstFailingContract': LAST_FAULT['message'][:160]} if kind == 'fault' else {})})
        hostile = [r for r in rows if not r['tamper'].startswith('EQUIVALENT')]
        self.report['tamper'] = {'cases': len(rows), 'hostileRejected': len(hostile), 'equivalentAccepted': sum(1 for r in rows if r['observed'] is True),
                                 'equivalentWithForgedSummaryRejected': sum(1 for r in rows if r['tamper'].startswith('EQUIVALENT') and r['observed'] != True),
                                 'modes': list(modes), 'rows': rows}

    # -------------------------------------------------------------- phase: semantic, scanner and source negatives
    def negatives(self):
        directory = self.directory / 'negative-sources'
        directory.mkdir()
        results = {}

        def attempt(label, data, codes, pages=None, name=None):
            path = directory / ((name or label) + '.pdf')
            path.write_bytes(data)
            run = self.directory / 'negative-runs' / label
            document = authored({'x': path}, pages or [('x', 1, 0)])
            code = refused(lambda: self.run(document, 'negative-runs/' + label), codes, label)
            assert not (run / 'assembled.pdf').exists(), label + ' published a PDF'
            assert json.loads((run / 'result.json').read_text())['status'] == 'failed'
            results[label] = code

        (self.directory / 'negative-runs').mkdir()
        for label, (data, codes) in literal.NEGATIVES.items():
            attempt(label, data, codes)
        report = (FIXTURES / 'report.pdf')
        for label, args in {'encrypted-empty-user-password': ['', 'owner'], 'encrypted-user-password': ['user', 'owner']}.items():
            out = directory / (label + '.pdf')
            subprocess.run([self.qpdf, '--encrypt', *args, '256', '--', str(report), str(out)], check=True, capture_output=True, timeout=60)
            attempt(label, out.read_bytes(), {'ENCRYPTED_PDF'})
        out = directory / 'encrypted-owner-restricted.pdf'
        subprocess.run([self.qpdf, '--encrypt', '', 'owner', '256', '--modify=none', '--extract=n', '--', str(report), str(out)], check=True, capture_output=True, timeout=60)
        attempt('encrypted-owner-restricted', out.read_bytes(), {'ENCRYPTED_PDF'})
        cover = (FIXTURES / 'cover.pdf').read_bytes()
        attempt('damaged-no-startxref-needs-recovery', cover[:cover.index(b'xref\n')] + b'%%EOF\n', {'INVALID_PDF_SOURCE'})
        attempt('malformed-pdf', b'%PDF-1.7\nnot a PDF document\n', {'INVALID_PDF_SOURCE', 'PDF_REPAIRED'})
        attempt('not-a-pdf-header', b'hello world\n', {'INVALID_PDF_SOURCE'})
        attempt('over-source-byte-limit', b'%PDF-1.7\n' + bytes(16 * 1024 * 1024), {'INVALID_PDF_SOURCE'})
        attempt('page-past-the-end', report.read_bytes(), {'PDF_PAGE_RANGE'}, pages=[('x', 5, 0)], name='range')
        attempt('over-500-pages', literal.many(501), {'PDF_PAGE_LIMIT'}, pages=[('x', 1, 0)])
        attempt('pixel-budget-134-a4-pages', cover, {'PDF_PIXEL_LIMIT'}, pages=[('x', 1, 0)] * 134, name='budget')
        attempt('prohibited-unselected-sibling-selected', literal.sibling_prohibited(), {'PDF_PAGE_FEATURE_UNSUPPORTED'}, pages=[('x', 2, 0)], name='sibling')
        missing = refused(lambda: self.run(authored({'x': directory / 'missing.pdf'}, [('x', 1, 0)]), 'negative-runs/missing-source'), {'INVALID_PDF_SOURCE'}, 'missing')
        results['missing-source-file'] = missing
        link = directory / 'link.pdf'
        link.symlink_to(directory / 'range.pdf')
        results['source-is-a-symlink'] = refused(lambda: self.run(authored({'x': link}, [('x', 1, 0)]), 'negative-runs/symlink'), {'INVALID_PDF_SOURCE'}, 'symlink')
        # Documented post-assembly failures: admitted, assembled, then refused by the fresh observation. Never a verified publication.
        late = {}
        for label, (data, fragment) in literal.POST_ASSEMBLY.items():
            path = directory / (label + '.pdf')
            path.write_bytes(data)
            run = self.directory / 'negative-runs' / ('late-' + label)
            code = refused(lambda: self.run(authored({'x': path}, [('x', 1, 0)]), 'negative-runs/late-' + label), {'VERIFICATION_FAILED'}, label)
            assert fragment in LAST_FAULT['message'], (label, LAST_FAULT)
            assert json.loads((run / 'result.json').read_text())['status'] == 'failed' and not (run / 'verification.json').exists(), label
            late[label] = {'fault': code, 'assembledPdfLeftBehind': (run / 'assembled.pdf').exists(), 'receiptWritten': False, 'message': LAST_FAULT['message'][:120]}
        results['post-assembly-failures'] = late
        # Accepted although they look risky or rich: ordinary names, discarded document data, an unselected prohibited sibling.
        accepted = {}
        for label, data in literal.POSITIVES.items():
            path = directory / (label + '.pdf')
            path.write_bytes(data)
            self.run(authored({'x': path}, [('x', 1, 0)]), 'positive-' + label)
            self.verified('positive-' + label)
            catalogue = self.qpdf_json(self.directory / ('positive-' + label) / 'assembled.pdf')
            root = catalogue['qpdf'][1]['obj:' + catalogue['qpdf'][1]['trailer']['value']['/Root']]['value']
            assert set(root) == {'/Type', '/Pages'}, root
            accepted[label] = sorted(json.loads((self.directory / ('positive-' + label) / 'assembly-summary.json').read_text())['sources'][0]['discarded'])
        sibling = directory / 'sibling-ok.pdf'
        sibling.write_bytes(literal.sibling_prohibited())
        self.run(authored({'x': sibling}, [('x', 1, 0)]), 'positive-unselected-sibling')
        self.verified('positive-unselected-sibling')
        accepted['unselected-prohibited-sibling'] = 'accepted when only the clean page is selected'
        # Exact repeat accounting: 133 A4 pages fit the 16,777,216 pixel budget; 134 were refused above.
        fit = directory / 'budget-fit.pdf'
        fit.write_bytes(cover)
        started = time.monotonic()
        self.run(authored({'x': fit}, [('x', 1, 0)] * 133), 'positive-133-a4-repeats', timeout=300)
        self.verified('positive-133-a4-repeats')
        accepted['133-a4-repeats'] = round(time.monotonic() - started, 1)
        # Aggregate-source parity (the supervisor's reproduction): three valid sources, each under 16 MiB, total over 32 MiB. A new run refuses them;
        # saved verification of a run whose retained captured bytes and digests were replaced and refreshed must refuse them identically.
        names = ['one', 'two', 'three']
        small = {n: directory / ('parity-%s.pdf' % n) for n in names}
        for path in small.values():
            path.write_bytes(literal.single(b'Parity'))
        pages = [(n, 1, 0) for n in names]
        self.run(authored(small, pages), 'parity-base')
        self.verified('parity-base')
        big = literal.padded(11 * 1024 * 1024 + 700000)
        assert 3 * len(big) > adaptor.MAX_TOTAL_SOURCE_BYTES and len(big) < adaptor.MAX_SOURCE_BYTES
        clone = self.directory / 'parity-padded'
        self.clone(self.directory / 'parity-base', clone)
        capture = json.loads((clone / 'capture.json').read_text())
        receipt = json.loads((clone / 'verification.json').read_text())
        for entry in capture['sources']:
            (clone / ('source-%s.pdf' % entry['name'])).write_bytes(big)
            entry['bytes'], entry['sha256'] = len(big), sha(big)
            receipt['evidence']['source-%s.pdf' % entry['name']] = sha(big)
        atomic_json(clone / 'capture.json', capture)
        receipt['evidence']['capture.json'] = sha((clone / 'capture.json').read_bytes())
        atomic_json(clone / 'verification.json', receipt)
        kind, code = outcome(lambda: registry.verify(clone))
        assert (kind, code) == ('fault', 'VERIFICATION_FAILED') and 'retained captured source three' in LAST_FAULT['location'], (kind, code, LAST_FAULT)
        raw_kind, raw_code = outcome(lambda: adaptor.verify_semantic(clone, {'qpdf': self.qpdf, 'mupdf': self.mupdf}))
        assert (raw_kind, raw_code) == ('fault', 'VERIFICATION_FAILED'), (raw_kind, raw_code)
        for path in small.values():
            path.write_bytes(big)
        kind, rerun = outcome(lambda: self.run(authored(small, pages), 'parity-rerun'))
        assert (kind, rerun, LAST_FAULT['location']) == ('fault', 'INVALID_PDF_SOURCE', '$.sources[2].path'), (kind, rerun, LAST_FAULT)
        # Header parity: a retained captured source without the standard header is refused by verification before any native launch.
        headerless = self.directory / 'parity-headerless'
        self.clone(self.directory / 'parity-base', headerless)
        (headerless / 'source-one.pdf').write_bytes(b'NOT A PDF\n' + (headerless / 'source-one.pdf').read_bytes())
        kind, code = outcome(lambda: registry.verify(headerless))
        assert (kind, code) == ('fault', 'VERIFICATION_FAILED'), (kind, code)
        self.report['sourceBudgetParity'] = {'capturedBytes': 3 * len(big), 'limit': adaptor.MAX_TOTAL_SOURCE_BYTES, 'perSourceBytes': len(big),
                                              'savedVerification': code, 'newRunOnSameBytes': rerun, 'headerlessRetainedSource': 'VERIFICATION_FAILED'}
        self.report['negatives'] = {'refused': results, 'accepted': accepted}

    # -------------------------------------------------------------- phase: runtimes and retained-evidence authority
    def runtime(self):
        report = {}
        document = authored(self.sources, [('cover', 1, 0), ('report', 2, 0)])
        self.configure({}, 'rt-start-empty.json')          # only the explicit run locations may supply executables below
        report['runWithoutQpdf'] = refused(lambda: self.run(document, 'rt-no-qpdf', locations={'mupdf': self.mupdf}), {'INTERPRETER_NOT_FOUND'})
        report['runWithoutMupdf'] = refused(lambda: self.run(document, 'rt-no-mupdf', locations={'qpdf': self.qpdf}), {'INTERPRETER_NOT_FOUND'})
        report['runWrongQpdf'] = refused(lambda: self.run(document, 'rt-wrong-qpdf', locations={**self.locations, 'qpdf': self.fake('q999', 'echo "qpdf version 9.9.9"\n')}), {'UNSUPPORTED_RUNTIME'})
        report['runSystemMutool'] = refused(lambda: self.run(document, 'rt-wrong-mupdf', locations={**self.locations, 'mupdf': self.fake('m123', 'echo "mutool version 1.23.10" >&2\n')}), {'UNSUPPORTED_RUNTIME'})
        report['runRelativePath'] = refused(lambda: self.run(document, 'rt-relative', locations={**self.locations, 'qpdf': 'qpdf'}), {'INTERPRETER_NOT_FOUND'})
        self.run(document, 'rt-good')
        run = self.directory / 'rt-good'
        self.configure({}, 'empty-config.json')
        report['verifyWithoutAnyRuntime'] = refused(lambda: registry.verify(run), {'INTERPRETER_NOT_FOUND'})
        self.configure({'qpdf': self.qpdf}, 'qpdf-only.json')
        report['verifyWithoutMupdf'] = refused(lambda: registry.verify(run), {'INTERPRETER_NOT_FOUND'})
        self.configure({**self.locations, 'qpdf': self.fake('q888', 'echo "qpdf version 8.8.8"\n')}, 'wrong-qpdf.json')
        report['verifyWrongQpdf'] = refused(lambda: registry.verify(run), {'UNSUPPORTED_RUNTIME'})
        self.configure({**self.locations, 'mupdf': self.fake('m124', 'echo "mutool version 1.24.0" >&2\n')}, 'wrong-mupdf.json')
        report['verifyWrongMupdf'] = refused(lambda: registry.verify(run), {'UNSUPPORTED_RUNTIME'})
        self.configure({}, 'empty-config-2.json')
        os.environ.update(SCHEMAXIS_QPDF=self.qpdf, SCHEMAXIS_MUPDF=self.mupdf)
        report['verifyWithDocumentedEnvironment'] = registry.verify(run)['verified']
        # Receipt and retained-submission executable strings are inert: a canary script must never run.
        canary = self.directory / 'CANARY'
        evil = self.fake('evil', 'touch %s\necho "qpdf version 12.4.2"\n' % canary)
        forged = self.directory / 'forged-executable'
        self.clone(run, forged)
        receipt = json.loads((forged / 'verification.json').read_text())
        receipt['executables'] = {'qpdf': evil, 'mupdf': evil}
        submission = json.loads((forged / 'assemble-submission.json').read_text())
        submission['nativeCommand'] = [evil, '--version']
        submission['interpreter'] = {'executable': evil}
        atomic_json(forged / 'assemble-submission.json', submission)
        receipt['evidence']['assemble-submission.json'] = sha((forged / 'assemble-submission.json').read_bytes())
        atomic_json(forged / 'verification.json', receipt)
        self.configure(self.locations, 'config.json')
        assert registry.verify(forged)['verified'] is True
        assert not canary.exists(), 'a receipt executable was run'
        report['forgedReceiptExecutableNeverRun'] = True
        # Retained diagnostics: each documented check is enforced, and unrelated retained files are not silently trusted.
        diagnostics = {}
        def mutate(label, change, public=('VERIFICATION_FAILED',), product=('VERIFICATION_FAILED',)):
            """The public route may fail earlier in a shared contract (run storage); the product verifier is also called directly."""
            copy_ = self.directory / ('diagnostic--' + label)
            self.clone(run, copy_)
            change(copy_)
            diagnostics[label] = {'publicRoute': refused(lambda: registry.verify(copy_), set(public), label),
                                  'productVerifier': refused(lambda: adaptor.verify_semantic(copy_, {'qpdf': self.qpdf, 'mupdf': self.mupdf}), set(product), label + ' (raw)')}
        mutate('plan-differs', lambda d: atomic_json(d / 'plan.json', {**json.loads((d / 'plan.json').read_text()), 'operation': 'x'}))
        mutate('capture-record-differs', lambda d: atomic_json(d / 'capture.json', {'sources': []}))
        mutate('captured-source-bytes-differ', lambda d: (d / 'source-report.pdf').write_bytes((d / 'source-report.pdf').read_bytes() + b'\n%x\n'))
        mutate('receipt-publication-digest-differs', lambda d: atomic_json(d / 'verification.json', {**json.loads((d / 'verification.json').read_text()), 'artifacts': []}))
        mutate('summary-differs-from-fresh-observation', lambda d: (d / 'assembly-summary.json').write_bytes(adaptor.encode({**json.loads((d / 'assembly-summary.json').read_text()), 'dpi': 72})))
        mutate('retained-evidence-file-changed', lambda d: (d / 'assemble.stderr').write_bytes(b'tampered'))
        mutate('retained-evidence-file-missing', lambda d: (d / 'check-cover.stdout').unlink())
        mutate('authored-input-invalid', lambda d: atomic_json(d / 'authored.json', {'tampered': True}), public=('INVALID_SCHEMA_SNAPSHOT', 'VERIFICATION_FAILED'))
        mutate('incomplete-result', lambda d: atomic_json(d / 'result.json', {'status': 'incomplete', 'verified': False}), public=('INCOMPLETE_EXECUTION',), product=('INCOMPLETE_EXECUTION',))
        report['retainedDiagnostics'] = diagnostics
        self.report['runtime'] = report

    # -------------------------------------------------------------- phase: timeout, cancellation and interrupted verification
    def lifecycle(self):
        report = {}
        document = authored(self.sources, [('cover', 1, 0), ('report', 2, 0), ('report', 3, 90)])
        report['runTimeoutBeforeFirstLaunch'] = refused(lambda: registry.run(document, self.directory / 'lc-timeout', locations=self.locations, timeout=1e-9), {'RUNNER_TIMED_OUT'})
        cancel = threading.Event()
        cancel.set()
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            report['runCancelledBeforeFirstLaunch'] = refused(lambda: registry.run(document, self.directory / 'lc-cancel', locations=self.locations, timeout=60), {'RUNNER_CANCELLED'})
        self.run(document, 'lc-base')
        base = self.directory / 'lc-base'
        paths = {'qpdf': self.qpdf, 'mupdf': self.mupdf}
        # Standalone verification deadline expiring part-way through its launches.
        stopped = []
        for budget in (0.15, 0.6, 1.2):
            started = time.monotonic()
            with execution_deadline(budget):
                code = refused(lambda: adaptor.verify_semantic(base, paths), {'RUNNER_TIMED_OUT'}, 'deadline %s' % budget)
            stopped.append({'budgetSeconds': budget, 'fault': code, 'elapsed': round(time.monotonic() - started, 2)})
        assert all(item['elapsed'] < item['budgetSeconds'] + 1.5 for item in stopped), stopped
        report['verifyDeadlineMidLaunches'] = stopped
        # Final host work expiring after every native launch has finished.
        original = adaptor.observe_all
        def slow_tail(*args, **kwargs):
            summary = original(*args, **kwargs)
            time.sleep(3)
            return summary
        adaptor.observe_all = slow_tail
        try:
            with execution_deadline(4):
                report['deadlineExpiresDuringFinalHostWork'] = refused(lambda: adaptor.verify_semantic(base, paths), {'RUNNER_TIMED_OUT'})
        finally:
            adaptor.observe_all = original
        # Cancellation reaches verification: before the first launch, and in flight inside a hung native observer.
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            report['verifyCancelledBeforeFirstLaunch'] = refused(lambda: adaptor.verify_semantic(base, paths), {'RUNNER_CANCELLED'})
        marker = '29.%06d' % (os.getpid() % 1000000)
        slow = self.fake('slow-mupdf', 'if [ "$1" = "-v" ]; then echo "mutool version 1.28.5" >&2; else exec sleep %s; fi\n' % marker)
        hung = threading.Event()
        cancel_in_flight = threading.Event()
        def cancel_when_hung():
            end = time.monotonic() + 40
            while time.monotonic() < end:
                if subprocess.run(['pgrep', '-f', 'sleep ' + marker], capture_output=True).stdout.strip():
                    hung.set()
                    cancel_in_flight.set()                          # the native observer is demonstrably running: cancel now
                    return
                time.sleep(.02)
        watcher = threading.Thread(target=cancel_when_hung)
        watcher.start()
        started = time.monotonic()
        with allocation({'threads': 1, 'ranks': 1}, cancel_in_flight):
            report['verifyCancelledInFlight'] = refused(lambda: adaptor.verify_semantic(base, {'qpdf': self.qpdf, 'mupdf': slow}), {'RUNNER_CANCELLED'})
        watcher.join()
        assert hung.is_set(), 'the hung native observer was never observed'
        time.sleep(.5)
        assert not subprocess.run(['pgrep', '-f', 'sleep ' + marker], capture_output=True).stdout.strip(), 'a cancelled native process survived'
        report['cancelledInFlightSeconds'] = round(time.monotonic() - started, 1)
        report['cancelledNativeProcessGroupGone'] = True
        # One cumulative deadline covers assembly and its fresh observation: a hung observer ends the whole run at the timeout.
        started = time.monotonic()
        code = refused(lambda: registry.run(document, self.directory / 'lc-hung', locations={**self.locations, 'mupdf': slow}, timeout=6), {'RUNNER_TIMED_OUT'})
        elapsed = time.monotonic() - started
        assert elapsed < 10, elapsed
        report['runWithHungObserver'] = {'fault': code, 'elapsedSeconds': round(elapsed, 1), 'timeoutSeconds': 6}
        report['failedRunEvidenceRetained'] = json.loads((self.directory / 'lc-hung/result.json').read_text())['status'] == 'failed'
        time.sleep(.5)
        assert not subprocess.run(['pgrep', '-f', 'sleep ' + marker], capture_output=True).stdout.strip(), 'a timed-out native process survived'
        self.report['lifecycle'] = report

    # -------------------------------------------------------------- phase: shared entry boundaries, workflow, reuse, handoff
    def boundaries(self):
        report = {}
        document = authored(self.sources, [('cover', 1, 0), ('report', 2, 0), ('report', 3, 90)])
        direct = adaptor.run(document, self.directory / 'bd-direct', executable=self.qpdf, oracle=self.mupdf, timeout=120)
        assert direct['verified'] is True
        report['directAdaptorRun'] = 'verified'
        self.run(document, 'bd-registry')
        self.verified('bd-registry')
        report['registryRun'] = 'verified'
        # Finite composition: an axis and a definition resolve before planning; two states, each verified.
        study = copy.deepcopy(document)
        study['definitions'] = {'quarter': 90}
        study['axes'] = [{'name': 'turn', 'values': [0, 180]}]
        study['pages'][0]['rotate'] = {'$axis': 'turn'}
        study['pages'][1]['rotate'] = {'$document': '/definitions/quarter'}
        result = self.run(study, 'bd-study')
        assert len(result['states']) == 2, result
        registry.verify(self.directory / 'bd-study')
        report['finiteStudy'] = {'states': 2, 'verified': True}
        # Workflow: reuse of unchanged work, and invalidation when captured source bytes change at the same path.
        working = self.directory / 'bd-sources'
        working.mkdir()
        shutil.copy(FIXTURES / 'cover.pdf', working / 'cover.pdf')
        shutil.copy(FIXTURES / 'report.pdf', working / 'report.pdf')
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'packet', 'document': authored({'cover': working / 'cover.pdf', 'report': working / 'report.pdf'}, [('cover', 1, 0), ('report', 3, 90)])}]}
        first = workflow.execute(graph, self.directory / 'bd-workflow', locations=self.locations, timeout=120)
        assert workflow.verify(self.directory / 'bd-workflow')['verified']
        again = workflow.execute(graph, self.directory / 'bd-workflow', locations=self.locations, timeout=120, resume=True)
        assert again['jobs'][0]['reused'] is True
        changed = (working / 'cover.pdf').read_bytes() + b'\n%a different captured identity\n'
        (working / 'cover.pdf').write_bytes(changed)
        after = workflow.execute(graph, self.directory / 'bd-workflow', locations=self.locations, timeout=120, resume=True)
        assert after['jobs'][0]['reused'] is False
        assert workflow.verify(self.directory / 'bd-workflow')['verified']
        report['workflow'] = {'first': first['status'], 'unchangedReused': True, 'samePathChangedBytesReused': False}
        # Scheduler: independent assemblies run concurrently, a dependent one waits, then everything is reused on resume and re-verified.
        shutil.copy(FIXTURES / 'cover.pdf', working / 'cover.pdf')
        parallel_graph = {'version': 'schemaxis.workflow/1', 'execution': {'maxWorkers': 2, 'memoryMB': 4096},
                          'operations': [{'id': 'one', 'document': authored(self.sources, [('cover', 1, 0), ('report', 2, 0)])},
                                         {'id': 'two', 'document': authored({'report': self.sources['report']}, [('report', 4, 90), ('report', 1, 0)])},
                                         {'id': 'three', 'document': {**authored({'first': self.directory / 'unused.pdf'}, [('first', 1, 0)]),
                                                                       'sources': [{'name': 'first', 'path': {'$artifact': 'one', 'index': 0}}]}}]}
        scheduled = workflow.execute(parallel_graph, self.directory / 'bd-parallel', locations=self.locations, timeout=180)
        assert workflow.verify(self.directory / 'bd-parallel')['verified']
        resumed = workflow.execute(parallel_graph, self.directory / 'bd-parallel', locations=self.locations, timeout=180, resume=True)
        assert all(job['reused'] for job in resumed['jobs']), resumed['jobs']
        assert workflow.verify(self.directory / 'bd-parallel')['verified']
        report['scheduler'] = {'status': scheduled['status'], 'jobs': len(scheduled['jobs']), 'resumedAllReused': True, 'postVerified': True}
        # Actual handoffs: QPDF to QPDF, and QPDF to MuPDF review of the verified published PDF.
        chain = json.loads((ROOT / 'examples/schemaxis/qpdf-chain.json').read_text())
        for operation in chain['operations']:
            for entry in operation['document']['sources']:
                if isinstance(entry['path'], str):
                    entry['path'] = str(FIXTURES / ('cover.pdf' if entry['name'] == 'cover' else 'report.pdf'))
        chained = workflow.execute(chain, self.directory / 'bd-chain', locations=self.locations, timeout=180)
        assert workflow.verify(self.directory / 'bd-chain')['verified']
        self.literal(self.published('bd-chain', 'second', 'assembled.pdf'), [('report', 3, 180), ('cover', 1, 0)])
        report['qpdfToQpdf'] = {'status': chained['status'], 'literalOracle': 'second output matches known pages'}
        handoff = json.loads((ROOT / 'examples/schemaxis/qpdf-to-mupdf.json').read_text())
        for entry in handoff['operations'][0]['document']['sources']:
            entry['path'] = str(FIXTURES / ('cover.pdf' if entry['name'] == 'cover' else 'report.pdf'))
        reviewed = workflow.execute(handoff, self.directory / 'bd-handoff', locations=self.locations, timeout=180)
        assert workflow.verify(self.directory / 'bd-handoff')['verified']
        def png_size(path):
            header = Path(path).read_bytes()[:24]
            assert header[:8] == b'\x89PNG\r\n\x1a\n'
            return list(struct.unpack('>II', header[16:24]))
        sizes = [png_size(self.published('bd-handoff', 'review', 'page-001.png')), png_size(self.published('bd-handoff', 'review', 'page-002.png'))]
        assert sizes == [[160, 240], [596, 842]], sizes       # published page 3 (report 3 turned 90) then page 1 (A4 cover), at 72 dpi
        report['qpdfToMupdf'] = {'status': reviewed['status'], 'reviewedPngSizes': sizes, 'scope': 'MuPDF reviewed the verified published PDF through an artifact binding.'}
        self.report['boundaries'] = report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qpdf', type=Path, required=True)
    parser.add_argument('--mupdf', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--phases', default=','.join(PHASES), help='comma list from: ' + ', '.join(PHASES))
    parser.add_argument('--register', action='store_true', help='register the kit receipt (only after the root source freeze)')
    args = parser.parse_args()
    chosen = [p for p in args.phases.split(',') if p]
    assert set(chosen) <= set(PHASES), chosen
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    q = Qualification(directory, args.qpdf.resolve(), args.mupdf.resolve())
    q.report['verified'] = False
    started = time.monotonic()
    try:
        for phase in chosen:
            began = time.monotonic()
            getattr(q, phase)()
            q.report.setdefault('seconds', {})[phase] = round(time.monotonic() - began, 1)
            print('phase %s passed in %.1fs' % (phase, time.monotonic() - began), flush=True)
        if args.register:
            assert 'kit' in chosen, 'registration needs the kit phase'
            q.report['registered'] = register(directory / 'kit/qualification.json')
        q.report['verified'] = set(chosen) == set(PHASES)
        q.report['phases'] = chosen
    finally:
        q.report['totalSeconds'] = round(time.monotonic() - started, 1)
        atomic_json(directory / 'acceptance.json', q.report)
    print(json.dumps({k: v for k, v in q.report.items() if k not in ('tamper', 'negatives')}, indent=2)[:4000])


if __name__ == '__main__':
    main()
