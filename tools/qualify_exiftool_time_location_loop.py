#!/usr/bin/env python3
"""Public author / plan / run / inspect / verify loop and workflow chains for the ExifTool time and location family, against a real ExifTool 13.55.

Part A drives ``python3 -m schemaxis agent`` with a deterministic local client (not a language-model evaluation): discovery (geotagging, clock correction and position
searches find the real operations; renaming, raw tags, expressions and reverse geocoding find none), valid drafts and plans of correctTime, setLocation and geotagFromTrack, real
public runs of each with revision-bound verification (a fresh native replay), outputs decoded from the published image bytes by this tool's own hand-written readers, small-page
inspection of the write report, and a refusal control. Part B runs the workflow scheduler chains of ``tests/unit/test_exiftool_e3_workflow.py`` (edit, correct, geotag, inspect and
audit through ``$artifact`` bindings, typed slots, plan artifacts, reuse and invalidation, folder and mixed folders, TRACK_RESOURCE_LIMIT at run time).
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
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit'), str(Path(__file__).resolve().parent)]
import exiftool_e3_fixtures as fx  # noqa: E402
from qualify_exiftool_write_loop import Loop  # noqa: E402
from test_exiftool_e3_gpx import doc as gpx  # noqa: E402

V = 'schemaxis.exiftool/1'
TRACK = gpx([[('0', '10.000', '2026-03-01T10:59:00Z', '10'), ('0', '10.002', '2026-03-01T11:01:00Z', '20'), ('0', '10.004', '2026-03-01T11:03:00Z', '30')]])
ROWS = []


def sha(data): return hashlib.sha256(data).hexdigest()


def row(identity, operation, supported, verified, outcome=None, **extra):
    """One finite report row. ``outcome`` is ``succeeded`` only for an actual successful operation case (``supported`` true) and ``refused`` only for a refusal the case proves;
    discovery and control rows carry neither and never vouch for support."""
    written = extra.pop('written', supported if (supported and operation in ('correctTime', 'setLocation', 'geotagFromTrack')) else None)
    ROWS.append({'id': identity, 'operation': operation, 'container': 'jpeg', 'supported': bool(supported), 'written': written, 'independentlyVerified': bool(verified),
                 **({'outcome': outcome} if outcome else {}), **extra})


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
    return value


def degrees(triple):
    (d, dd), (m, md), (s, sd) = triple
    return Fraction(d, dd) + Fraction(m, md) / 60 + Fraction(s, sd) / 3600


def search_all(loop, query):
    """Every capability id a query finds, following the pages (the route offers sixteen operations, more than one page)."""
    found, cursor = [], None
    while True:
        page = loop.call('capabilities.search', query=query, **({'cursor': cursor} if cursor else {}))
        found += [i['id'] for i in page['items']]
        cursor = page['page']['nextCursor']
        if cursor is None:
            return found


def discovery(loop):
    shown = {}
    for query, wanted in (('geotag photos', 'geotagFromTrack'), ('shift photo capture time', 'correctTime'), ('camera clock skew', 'reconcileTime'), ('where was this photo taken', 'locate'),
                          ('set photo location', 'setLocation')):
        found = search_all(loop, query)
        assert 'operation/exiftool/' + wanted in found, (query, found)
        shown[query] = found[:6]
    for query in ('reverse geocode photos', 'run a raw exiftool expression'):
        found = search_all(loop, query)
        assert not [i for i in found if i.startswith('operation/exiftool/')], (query, found)
        shown[query] = found
    loop.report['cases']['discovery'] = shown
    row('discovery-geotag-and-shift-positive', 'geotagFromTrack', False, True, kind='discovery-control')
    row('discovery-raw-expression-reverse-geocode-negative', 'inspectMetadata', False, True, kind='discovery-control')


def run_document(loop, label, document, expect='succeeded'):
    loop.author(document)
    return loop.run(label, expect=expect)


def part_a(root, config, exe):
    photos = root / 'private' / 'photos'
    photos.mkdir(parents=True)
    (photos / 'a1.jpg').write_bytes(fx.full_time(make='A'))
    (photos / 'b1.jpg').write_bytes(fx.full_time(make='B', off='+00:00', xmp=fx.xmp_properties(captured='2026-03-01T12:00:00.12+00:00'), iptc=[(2, 55, '20260301'), (2, 60, '120000+0000')]))
    (photos / 'walk.gpx').write_bytes(TRACK)
    loop = Loop(root, config)
    items = {'items': [{'id': 'a1', 'path': str(photos / 'a1.jpg')}, {'id': 'b1', 'path': str(photos / 'b1.jpg')}]}
    try:
        loop.call('methods')
        discovery(loop)
        loop.draft = loop.call('create_draft', provider='exiftool', name='time and location loop')
        loop.task = loop.call('create_task', objective='Correct clocks and place synthetic photos', allowed_providers=['exiftool'],
                              budget={'maxAttempts': 80, 'maxElapsedSeconds': 1500, 'timeoutPerStageSeconds': 300, 'maxRepeatedFailures': 10})
        # correctTime: dev1 (make A) +60 s, dev2 (make B) -60 s
        run = run_document(loop, 'correct-time', {'version': V, 'operation': 'correctTime', 'media': items, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}, {'group': 'dev2', 'shift': {'seconds': '-60'}}]})
        names = sorted(run['resources'])
        assert {'a1.jpg', 'b1.jpg', 'time-correction-plan.json', 'time-report.json', 'write-report.json', 'residual.json', 'manifest.json'} <= set(names) and 'time-report.csv' not in names, names
        a1, b1 = bytes_of(loop, run, 'a1.jpg'), bytes_of(loop, run, 'b1.jpg')
        assert (fx.exif_ascii(a1, 'ExifIFD', 0x9003), fx.exif_ascii(b1, 'ExifIFD', 0x9003)) == ('2026:03:01 12:01:00', '2026:03:01 11:59:00')
        assert fx.exif_ascii(a1, 'ExifIFD', 0x9291) == '12'                                          # the fraction is unchanged
        verified = verify(loop, run)
        report = loop.call('inspect_resource', resource_id=run['resources']['write-report.json']['id'], pointer='/items', offset=0, limit=1, max_bytes=2048)
        assert report['mode'] == 'members' and report['page']['returned'] == 1 and report['page']['total'] == 2, report
        row('loop-correct-time', 'correctTime', True, verified['verified'] and verified.get('nativeReplay') == 'fresh-replay-matched', outcome='succeeded')
        # setLocation: exact decimals within the 2e-10 degree bound
        run = run_document(loop, 'set-location', {'version': V, 'operation': 'setLocation', 'media': items, 'default': {'latitude': '10.5', 'longitude': '20.25', 'datum': 'WGS-84'}})
        data = bytes_of(loop, run, 'a1.jpg')
        assert abs(degrees(fx.exif_rationals(data, 'GPS', 2)) - Fraction('10.5')) <= Fraction(2, 10 ** 10) and abs(degrees(fx.exif_rationals(data, 'GPS', 4)) - Fraction('20.25')) <= Fraction(2, 10 ** 10)
        assert (fx.exif_ascii(data, 'GPS', 1), fx.exif_ascii(data, 'GPS', 3)) == ('N', 'E')
        verified = verify(loop, run)
        row('loop-set-location', 'setLocation', True, verified['verified'] and verified.get('nativeReplay') == 'fresh-replay-matched', outcome='succeeded')
        # geotagFromTrack: a1 at 11:00:00.12Z lies 0.12 s past the first... the recorded 12:00:00.12 +01:00 is 11:00:00.12Z, halfway between no fixes: it is 59 s past the first fix
        track = {'id': 'walk', 'path': str(photos / 'walk.gpx')}
        run = run_document(loop, 'geotag', {'version': V, 'operation': 'geotagFromTrack', 'media': {'items': [items['items'][0]]}, 'tracks': [track]})
        data = bytes_of(loop, run, 'a1.jpg')
        # 11:00:00.12Z is 1.0001 minutes... between 10:59:00Z (10.000) and 11:01:00Z (10.002): 60.12 s of 120 s -> 10.000 + 0.002 * 60.12 / 120 = 10.001002
        assert abs(degrees(fx.exif_rationals(data, 'GPS', 4)) - Fraction(10001002, 10 ** 6)) <= Fraction(2, 10 ** 10), degrees(fx.exif_rationals(data, 'GPS', 4))
        assert fx.exif_rationals(data, 'GPS', 2) == [(0, 1), (0, 1), (0, 1)]
        verified = verify(loop, run)
        row('loop-geotag-from-track', 'geotagFromTrack', True, verified['verified'] and verified.get('nativeReplay') == 'fresh-replay-matched', outcome='succeeded')
        # reconcileTime and locate through the public loop: hand-literal values (a1 records 12:00:00.12 +01:00 = 11:00:00.12Z, b1 records 12:00:00.12 +00:00 = 12:00:00.12Z, both true at 11:00:00Z)
        (photos / 'g1.jpg').write_bytes(fx.jpeg(exif_version=b'0300', make='G', gps=fx.TOKYO))
        run = run_document(loop, 'reconcile-time', {'version': V, 'operation': 'reconcileTime', 'media': items, 'references': [{'item': 'a1', 'trueUtc': '2026-03-01T11:00:00Z'}, {'item': 'b1', 'trueUtc': '2026-03-01T11:00:00Z'}]})
        groups = {g['id']: g['skewSeconds'] for g in loop.document(run, 'time-report.json')['report']['groups']}
        assert (Fraction(groups['dev1']), Fraction(groups['dev2'])) == (Fraction('0.12'), Fraction('3600.12')), groups
        verified = verify(loop, run)
        row('loop-reconcile-time', 'reconcileTime', True, verified['verified'] and verified.get('nativeReplay') == 'fresh-replay-matched', outcome='succeeded', written=False)
        run = run_document(loop, 'locate', {'version': V, 'operation': 'locate', 'media': {'items': [{'id': 'g1', 'path': str(photos / 'g1.jpg')}]}})
        located = loop.document(run, 'location-report.json')['items'][0]
        assert (Fraction(located['position']['latitude']), Fraction(located['position']['longitude']), Fraction(located['height']['meters']), located['height']['reference']) == (Fraction('35.5'), Fraction('139.25'), Fraction('52.3'), 'ellipsoidal'), located
        verified = verify(loop, run)
        row('loop-locate', 'locate', True, verified['verified'] and verified.get('nativeReplay') == 'fresh-replay-matched', outcome='succeeded', written=False)
        # a plan-only run publishes documents and no image
        run = run_document(loop, 'geotag-plan', {'version': V, 'operation': 'geotagFromTrack', 'media': {'items': [items['items'][0]]}, 'tracks': [track], 'apply': 'plan'})
        assert sorted(run['resources']) == ['geotag-plan.json', 'manifest.json', 'track-report.json'], sorted(run['resources'])
        assert not [n for n in run['resources'] if n.endswith('.jpg')]
        verify(loop, run)
        # stale revision control
        plan = loop.plan()
        loop.author({'version': V, 'operation': 'setLocation', 'media': items, 'default': {'latitude': '11', 'longitude': '21'}})
        stale = loop.fault('STALE_REVISION', 'execute', plan_id=plan['id'], expected_revision=plan['revision'])
        # refusal control: every item refused by policy fails the run, publishes no image and is never support
        (photos / 'bare.jpg').write_bytes(fx.jpeg(make='C', dto=None, create=None, sub=None, xmp=None, iptc=None))
        loop.author({'version': V, 'operation': 'correctTime', 'media': {'items': [{'id': 'bare', 'path': str(photos / 'bare.jpg')}]}, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}], 'policies': {'uncorrectedItems': 'refuseSlot'}})
        failed = loop.run('refusal-control', expect='failed')
        fault = loop.call('observe', job_id=failed['job'], section='fault')['value']
        code = fault['code']
        assert code == 'NO_USABLE_ITEMS', fault
        row('loop-correct-time-all-refused', 'correctTime', False, True, outcome='refused', kind='refusal', faultCode=code, written=False)       # the run failed with no image published
        loop.report['cases']['loop'] = {'staleExecute': stale['code'], 'refusalFault': code, 'runs': [r['label'] for r in loop.report['runs']]}
    finally:
        try:
            loop.client.close()
        except Exception as error:
            loop.report['closeNote'] = str(error)[:200]
    return loop.report


def part_b():
    import test_exiftool_e3_workflow as module
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.Chain)
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
    positives = {'W1': ('correctTime', 'edit, correct, geotag, inspect and audit chain'), 'W2': ('correctTime', 'correctTime producer wrote an image that the inspectMetadata consumer read'),
                 'W3': ('correctTime', 'published plan bound as a text artifact and applied'), 'W4': ('geotagFromTrack', 'unchanged resume and modification time only'),
                 'W5': ('geotagFromTrack', 'changed GPX, plan, photo and membership invalidation'), 'W5b': ('geotagFromTrack', 'clock plan named by a geotag plan: reuse input and pin'),
                 'W6': ('setLocation', 'folder and mixed folder')}
    failed = {str(t).split('(')[0].strip() for t, _ in result.failures + result.errors}
    for key, (operation, note) in positives.items():
        data = module.Chain.RESULTS.get(key)
        ok = data is not None and data.get('independentlyVerified', False) and not any(key in name for name in failed)
        row('workflow-' + key, operation, ok, ok, outcome='succeeded' if ok else None, kind='workflow-chain', chainOperations=None if data is None else data['operation'], note=note)
    for key, (operation, code, note, written) in {'W2': ('correctTime', 'INVALID_PHOTO_SOURCE', 'the refused item\'s outcome slot bound to an image consumer is refused, never read as another photo', None),
                                                   'W7': ('geotagFromTrack', 'TRACK_RESOURCE_LIMIT', 'a track beyond a parser limit fails the run before anything is written', False)}.items():
        data = module.Chain.RESULTS.get(key)
        ok = data is not None and not any(key in name for name in failed)
        row('workflow-%s-control' % key, operation, False, ok, kind='workflow-control', faultCode=code, note=note, written=written, **({'outcome': 'refused'} if key == 'W7' else {}))
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
