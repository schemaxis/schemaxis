#!/usr/bin/env python3
"""Public author / plan / run / inspect / verify loop and workflow chains for the ExifTool copy, sidecar and naming family, against a real ExifTool 13.55.

Part A drives ``python3 -m schemaxis agent`` with a deterministic local client (not a language-model evaluation): discovery (naming, sidecar export and copying searches find the real
operations; raw tags, expressions and reverse geocoding find none), valid drafts and plans of the five operations, real public runs of each with revision-bound verification (a fresh
native replay), outputs decoded from the published bytes by this tool's own hand-written readers, small-page inspection of a report, a stale-revision control and a refusal control.
Part B runs the workflow scheduler chains of ``tests/unit/test_exiftool_e4_workflow.py`` (inspect, copy and audit; export, apply and compare; correct, plan and organise; minimise and
organise; typed slots; reuse and invalidation).
The report lists finite stable case rows: ``id``, ``operation`` (a declared simple operation), ``container`` (jpeg), ``supported`` (an actual successful operation case) or a refusal
control (``supported`` false, ``written`` false, with its fault code), and ``independentlyVerified``. A verified refusal never vouches for support, and the composite chains list their
member operations descriptively next to at least one declared single-operation row each.
Every run uses a unique private fixture folder under ``--output-directory``. Expected values are hand-written literals. Nothing here certifies photo provenance, time, location,
privacy or exhaustive ExifTool behaviour.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit'), str(Path(__file__).resolve().parent)]
import exiftool_e4_fixtures as f  # noqa: E402
from qualify_exiftool_write_loop import Loop  # noqa: E402

V = 'schemaxis.exiftool/1'
ROWS = []
WRITING = ('copyMetadata', 'applySidecar', 'exportSidecar', 'organiseCopies')


def sha(data): return hashlib.sha256(data).hexdigest()


def row(identity, operation, supported, verified, outcome=None, **extra):
    """One finite report row. ``outcome`` is ``succeeded`` only for an actual successful operation case (``supported`` true) and ``refused`` only for a refusal the case proves."""
    written = extra.pop('written', supported if (supported and operation in WRITING) else None)
    ROWS.append({'id': identity, 'operation': operation, 'container': 'jpeg', 'supported': bool(supported), 'written': written, 'independentlyVerified': bool(verified), **({'outcome': outcome} if outcome else {}), **extra})


def bytes_of(loop, run, name):
    resource = run['resources'][name]
    data, offset = b'', 0
    while offset is not None:
        part = loop.call('resource', resource_id=resource['id'], offset=offset, length=16384)
        data += base64.b64decode(part['data'])
        offset = part['nextOffset']
    assert sha(data) == resource['sha256'] and len(data) == resource['bytes'], name
    return data


def verify(loop, run):
    value = loop.call('verify', job_id=run['job'])['value']
    assert value['verified'] is True, value
    return value['verified'] and value.get('nativeReplay') == 'fresh-replay-matched'


def discovery(loop):
    shown = {}
    for query, wanted in (('rename photos', 'planNames'), ('export XMP sidecar', 'exportSidecar'), ('organise photos', 'organiseCopies'), ('apply XMP sidecar to photo', 'applySidecar'), ('copy photo metadata', 'copyMetadata')):
        found = [i['id'] for i in loop.call('capabilities.search', query=query)['items']]
        assert 'operation/exiftool/' + wanted in found, (query, found)
        shown[query] = found[:6]
    for query in ('reverse geocode photos', 'run a raw exiftool expression', 'shell expression to shift dates'):
        found = [i['id'] for i in loop.call('capabilities.search', query=query)['items']]
        assert not [i for i in found if i.startswith('operation/exiftool/')], (query, found)
        shown[query] = found
    loop.report['cases']['discovery'] = shown
    row('discovery-naming-sidecar-copy-positive', 'planNames', False, True, kind='discovery-control')
    row('discovery-raw-expression-reverse-geocode-negative', 'inspectMetadata', False, True, kind='discovery-control')


def run_document(loop, label, document, expect='succeeded'):
    loop.author(document)
    return loop.run(label, expect=expect)


def part_a(root, config, exe):
    photos = root / 'private' / 'photos'
    photos.mkdir(parents=True)
    (photos / 'a.jpg').write_bytes(f.master())
    (photos / 'b.jpg').write_bytes(f.plain())
    (photos / 'c.jpg').write_bytes(f.fx.jpeg(make='M', model='M', dto='2024:03:01 10:20:30', off='+09:00', sub=None, seed=3))
    loop = Loop(root, config)
    one, both = {'items': [{'id': 'a', 'path': str(photos / 'a.jpg')}]}, {'items': [{'id': 'a', 'path': str(photos / 'a.jpg')}, {'id': 'b', 'path': str(photos / 'b.jpg')}]}
    groups = ['descriptive', 'rights', 'camera', 'exposure', 'deviceSerials']
    try:
        loop.call('methods')
        discovery(loop)
        loop.draft = loop.call('create_draft', provider='exiftool', name='copy sidecar and naming loop')
        loop.task = loop.call('create_task', objective='Export, apply, copy, name and organise synthetic photos', allowed_providers=['exiftool'],
                              budget={'maxAttempts': 80, 'maxElapsedSeconds': 1500, 'timeoutPerStageSeconds': 300, 'maxRepeatedFailures': 10})
        # exportSidecar: a hand-literal reading of the produced sidecar text
        run = run_document(loop, 'export-sidecar', {'version': V, 'operation': 'exportSidecar', 'media': one, 'transfer': {'groups': groups}})
        sidecar = bytes_of(loop, run, 'a.xmp')
        text = sidecar.decode('utf-8')
        assert '<exif:ExposureTime>10/30</exif:ExposureTime>' in text and '<tiff:Make>Canon</tiff:Make>' in text and '<exifEX:BodySerialNumber>B123</exifEX:BodySerialNumber>' in text, text
        assert '<rdf:li xml:lang="de-DE">Hafen</rdf:li>' in text and '<rdf:li>Ann; Bob</rdf:li>' in text
        row('loop-export-sidecar', 'exportSidecar', True, verify(loop, run), outcome='succeeded')
        report = loop.call('inspect_resource', resource_id=run['resources']['sidecar-report.json']['id'], pointer='/items', offset=0, limit=1, max_bytes=2048)
        assert report['mode'] == 'members' and report['page']['returned'] == 1, report
        # copyMetadata: hand-literal exact exposure pair and serial in the copy
        run = run_document(loop, 'copy-metadata', {'version': V, 'operation': 'copyMetadata', 'media': both, 'source': {'item': 'a'}, 'transfer': {'groups': groups}, 'policies': {'existing': 'replace'}})
        copy = bytes_of(loop, run, 'b.jpg')
        snap = f.snapshot(copy, groups=groups)
        assert (snap['exposureTime']['value'], snap['exposureBias']['value'], snap['bodySerialNumber']['value'], snap['keywords']['value']) == ((10, 30), (-2, 6), 'B123', ['k1', 'k2']), snap
        row('loop-copy-metadata', 'copyMetadata', True, verify(loop, run), outcome='succeeded')
        # applySidecar with the exported sidecar as the declared source
        side = photos / 'a-export.xmp'
        side.write_bytes(sidecar)
        run = run_document(loop, 'apply-sidecar', {'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 'b', 'path': str(photos / 'b.jpg'), 'sidecar': str(side)}]}, 'source': {'sidecar': 'declared'},
                                                    'transfer': {'groups': groups}, 'policies': {'existing': 'replace'}})
        applied = f.snapshot(bytes_of(loop, run, 'b.jpg'), groups=groups)
        assert (applied['title']['value']['text'], applied['exposureTime']['value'], applied['lensSerialNumber']['value']) == ('Harbour', (10, 30), 'L456'), applied
        row('loop-apply-sidecar', 'applySidecar', True, verify(loop, run), outcome='succeeded')
        # planNames and organiseCopies
        rule = {'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'captureTime'}]}
        run = run_document(loop, 'plan-names', {'version': V, 'operation': 'planNames', 'media': {'items': [{'id': 'c', 'path': str(photos / 'c.jpg')}]}, **rule})
        plan = loop.document(run, 'names-plan.json')
        assert plan['items'][0]['relativePath'] == '20240301_102030.jpg', plan['items'][0]
        row('loop-plan-names', 'planNames', True, verify(loop, run), outcome='succeeded', written=False)
        run = run_document(loop, 'organise-copies', {'version': V, 'operation': 'organiseCopies', 'media': {'items': [{'id': 'c', 'path': str(photos / 'c.jpg')}]}, 'names': rule})
        assert bytes_of(loop, run, '20240301_102030.jpg') == (photos / 'c.jpg').read_bytes()
        row('loop-organise-copies', 'organiseCopies', True, verify(loop, run), outcome='succeeded')
        # stale revision control
        stale_plan = loop.plan()
        loop.author({'version': V, 'operation': 'exportSidecar', 'media': one, 'transfer': {'groups': ['rating']}})
        stale = loop.fault('STALE_REVISION', 'execute', plan_id=stale_plan['id'], expected_revision=stale_plan['revision'])
        # refusal control: every item refused fails the run and publishes nothing (never support)
        (photos / 'bare.jpg').write_bytes(f.fx.jpeg(make='C', dto=None, create=None, sub=None, xmp=None, iptc=None, exif=False))
        loop.author({'version': V, 'operation': 'exportSidecar', 'media': {'items': [{'id': 'bare', 'path': str(photos / 'bare.jpg')}]}, 'transfer': {'groups': ['descriptive']}})
        failed = loop.run('refusal-control', expect='failed')
        code = loop.call('observe', job_id=failed['job'], section='fault')['value']['code']
        assert code == 'NO_USABLE_ITEMS', code
        row('loop-export-sidecar-all-refused', 'exportSidecar', False, True, outcome='refused', kind='refusal', faultCode=code, written=False)
        loop.report['cases']['loop'] = {'staleExecute': stale['code'], 'refusalFault': code, 'runs': [r['label'] for r in loop.report['runs']]}
    finally:
        try:
            loop.client.close()
        except Exception as error:
            loop.report['closeNote'] = str(error)[:200]
    return loop.report


def part_b():
    import test_exiftool_e4_workflow as module
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.Chain)
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
    positives = {'P1': ('copyMetadata', 'inspect, copy and audit chain'), 'P2': ('applySidecar', 'export, apply and compare round trip'), 'P3': ('planNames', 'correct, plan and organise chain'),
                 'P4': ('organiseCopies', 'minimise and organise chain')}
    failed = {str(t).split('(')[0].strip() for t, _ in result.failures + result.errors}
    for key, (operation, note) in positives.items():
        data = module.Chain.RESULTS.get(key)
        ok = data is not None and data.get('independentlyVerified', False) and not any(key in name for name in failed)
        row('workflow-' + key, operation, ok, ok, outcome='succeeded' if ok else None, kind='workflow-chain', chainOperations=None if data is None else data['operation'], note=note, written=None)
    return {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'wasSuccessful': result.wasSuccessful() and not result.skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--exiftool', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    exe = args.exiftool.resolve()
    os.environ['SCHEMAXIS_EXIFTOOL'] = str(exe)
    config = root / 'config.json'
    config.write_text(json.dumps({'version': 1, 'locations': {'exiftool': str(exe)}}))
    report = {'scope': __doc__.split('\n\n')[0], 'verified': False, 'startedAt': time.time(), 'runtime': {'script': exe.name, 'sha256': sha(exe.read_bytes())}}
    try:
        part = part_a(root, config, exe)
        report['loop'] = {k: part[k] for k in ('cases', 'runs')}
        report['workflowChains'] = part_b()
        report['cases'] = ROWS
        report['verified'] = report['workflowChains']['wasSuccessful'] and all(r['independentlyVerified'] for r in ROWS)
    finally:
        report['finishedAt'] = time.time()
        (root / 'acceptance.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: report.get(k) for k in ('verified', 'workflowChains')}, indent=1)[:2500])
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
