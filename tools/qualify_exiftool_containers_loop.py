#!/usr/bin/env python3
"""Public author / plan / run / inspect / verify loop of the ExifTool container family (TIFF, DNG, PNG, WebP, HEIF) against a real ExifTool 13.55.

It drives ``python3 -m schemaxis agent`` with a deterministic local client (not a language-model evaluation): discovery (container-specific searches find the real operations of the whole family;
raw tags, shell expressions and a maker raw format find none), valid drafts, source-only planning (a plan is made and read without being executed), real public runs of inspectMetadata, editMetadata,
removeMetadata (categories and PNG/WebP minimise), reconcileTime, locate, correctTime, setLocation, geotagFromTrack (with a captured GPX input), copyMetadata, exportSidecar, applySidecar, planNames
and organiseCopies over hand-built container fixtures with revision-bound verification (a fresh native replay), outputs decoded from the published bytes by this tool's own hand-written literals,
small-page inspection of reports, a stale-revision control, the named refusals and the portable workflow chains of ``tests/unit/test_exiftool_e5_workflow.py``. Every run uses a unique private fixture
folder under ``--output-directory``; expected values are hand-written literals.

The report lists finite stable case rows: ``id``, ``operation`` (a declared simple operation), ``container``, ``supported`` (an actual successful operation case) or a refusal control
(``supported`` false, ``written`` false, with its fault code), and ``independentlyVerified``. A verified refusal never vouches for support. The per-cell (operation by container) native evidence is the
qualifier's; a loop row over a mixed container set is a loop row and never stands in for a cell. Nothing here certifies photo provenance, time, location, privacy or exhaustive
ExifTool behaviour.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit'), str(Path(__file__).resolve().parent)]
import exiftool_e3_fixtures as e3  # noqa: E402
import exiftool_e4_fixtures as f4  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
from qualify_exiftool_write_loop import Loop, search_all  # noqa: E402
from test_exiftool_e3_geotag import EQUATOR  # noqa: E402
from test_exiftool_e5_ops import ascii_of, payloads, snapshot, total, xmp_value  # noqa: E402

V = 'schemaxis.exiftool/1'
ROWS = []
TITLE, ARTIST = 'Quarry gate north', 'B. Mason'
FILES = {'q.tif': (f.plain_tiff('<'), 'tiff', [f.STRIP]), 'q.dng': (f.dng(artist='A. Mason')[0], 'dng', [f.STRIP, b'VendorPrivate-0123']), 'q.png': (f.basic_png(), 'png', [f.GAMA, f.IDAT + f.IEND]),
         'q.webp': (f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.webp_exif(), f.webp_xmp()), 'webp', [f.ck(b'VP8 ', f.vp8())]),
         'q.heic': (f.heic_basic(with_metadata=True), 'heif', [b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]]), 'bare.heic': (f.heic_basic(), 'heif', [])}


def sha(data): return hashlib.sha256(data).hexdigest()


def row(identity, operation, container, supported, verified, outcome=None, **extra):
    """One finite report row; ``outcome`` is ``succeeded`` only for an actual successful operation case and ``refused`` only for a refusal the case proves."""
    written = extra.pop('written', None)
    ROWS.append({'id': identity, 'operation': operation, 'container': container, 'supported': bool(supported), 'written': written, 'independentlyVerified': bool(verified), **({'outcome': outcome} if outcome else {}), **extra})


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
    return value.get('nativeReplay') == 'fresh-replay-matched'


def discovery(loop):
    shown = {}
    for query in ('edit TIFF metadata', 'edit PNG metadata', 'WebP metadata', 'HEIC metadata', 'remove metadata from TIFF files', 'read DNG metadata'):
        found = search_all(loop, query)
        assert [i for i in found if i in ('operation/exiftool/editMetadata', 'operation/exiftool/inspectMetadata', 'operation/exiftool/removeMetadata')], (query, found)
        shown[query] = found[:8]
    for query, wanted in (('shift capture time of PNG files', 'operation/exiftool/correctTime'), ('set location of WebP photos', 'operation/exiftool/setLocation'), ('geotag TIFF photos from a GPX track', 'operation/exiftool/geotagFromTrack'),
                          ('copy metadata onto TIFF files', 'operation/exiftool/copyMetadata'), ('minimise PNG metadata', 'operation/exiftool/removeMetadata'), ('export XMP sidecar for DNG files', 'operation/exiftool/exportSidecar')):
        found = search_all(loop, query)
        assert wanted in found, (query, found)
        shown[query] = found[:8]
    for query in ('run a raw exiftool expression', 'edit CR2 raw file metadata'):
        found = search_all(loop, query)
        assert not [i for i in found if i in ('operation/exiftool/editMetadata', 'operation/exiftool/removeMetadata')], (query, found)
        shown[query] = found[:8]
    loop.report['cases']['discovery'] = shown
    row('discovery-container-positive', 'inspectMetadata', 'mixed', False, True, kind='discovery-control')
    row('discovery-raw-expression-and-maker-raw-negative', 'editMetadata', 'mixed', False, True, kind='discovery-control')


def run_document(loop, label, document, expect='succeeded'):
    loop.author(document)
    return loop.run(label, expect=expect)


KINDS = ('tiff', 'dng', 'png', 'webp', 'heif')
EXT = t.EXTENSIONS
RICH_XMP = e3.xmp_properties(captured='2026-03-01T12:00:00.12+01:00', extra=f4.lang_alt('dc:title', 'Harbour') + f4.bag('dc:subject', 'k1', 'k2'))


def family(loop, root, photos):
    """The whole current family through the public agent: every operation over container items, decoded from the published bytes."""
    media = root / 'private' / 'family'
    media.mkdir(parents=True)
    rich = {k: media / ('r' + k + EXT[k]) for k in KINDS}
    for k, path in rich.items():
        path.write_bytes(t.full_time(k, gps=t.TOKYO, xmp=RICH_XMP, serial='SN-0001'))
    items = {'items': [{'id': 'r' + k, 'path': str(path)} for k, path in rich.items()]}
    master = media / 'master.jpg'
    master.write_bytes(f4.master())
    # source-only planning: a plan is made and read without being executed, and the draft stays valid
    loop.author({'version': V, 'operation': 'correctTime', 'media': items, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '3600'}}]})
    plan = loop.plan()
    assert plan['id'] and plan['revision'] is not None
    row('loop-source-only-plan-correct-time', 'correctTime', 'mixed', False, True, kind='planning-control', written=False)
    # read-only analysis over the mixed set, paged one item at a time
    run = run_document(loop, 'reconcile-time', {'version': V, 'operation': 'reconcileTime', 'media': items})
    report = loop.document(run, 'time-report.json', '/report/items')
    assert [(r['recordedLocal'], r['recordedOffset']) for r in report] == [('2026-03-01T12:00:00.12', '+01:00')] * 5, report
    page = loop.call('inspect_resource', resource_id=run['resources']['time-report.json']['id'], pointer='/report', offset=0, limit=1, max_bytes=2048)
    assert page['mode'] == 'members' and page['page']['returned'] == 1, page
    row('loop-reconcile-time', 'reconcileTime', 'mixed', True, verify(loop, run), outcome='succeeded', written=False)
    run = run_document(loop, 'locate', {'version': V, 'operation': 'locate', 'media': items})
    positions = [(r['position']['latitude'], r['position']['longitude']) for r in loop.document(run, 'location-report.json', '/items')]
    assert positions == [('35.5', '139.25')] * 5, positions
    row('loop-locate', 'locate', 'mixed', True, verify(loop, run), outcome='succeeded', written=False)
    # correctTime: 12:00:00 + 3600 s on every container
    run = run_document(loop, 'correct-time', {'version': V, 'operation': 'correctTime', 'media': items, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '3600'}}]})
    for k in KINDS:
        data = bytes_of(loop, run, 'r' + k + EXT[k])
        assert ascii_of(data, 'ExifIFD', 0x9003) == '2026:03:01 13:00:00' and xmp_value(data, 'photoshop:DateCreated') == '2026-03-01T13:00:00.12+01:00', k
    row('loop-correct-time', 'correctTime', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    # setLocation: one position on every container
    run = run_document(loop, 'set-location', {'version': V, 'operation': 'setLocation', 'media': items, 'default': {'latitude': '35.658581', 'longitude': '139.745433'}})
    for k in KINDS:
        data = bytes_of(loop, run, 'r' + k + EXT[k])
        assert (ascii_of(data, 'GPS', 1), ascii_of(data, 'GPS', 3)) == ('N', 'E') and abs(total(data, 'GPS', 2) - __import__('fractions').Fraction('35.658581')) <= __import__('fractions').Fraction(2, 10 ** 10), k
    row('loop-set-location', 'setLocation', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    # geotagFromTrack with a captured GPX input: photos at 12:00:10 +09:00 sit at 10.001 E
    track = media / 'watch.gpx'
    track.write_bytes(EQUATOR)
    local = {k: media / ('g' + k + EXT[k]) for k in ('tiff', 'png', 'webp')}
    for k, path in local.items():
        kw = dict(dto='2026:03:01 12:00:10', off='+09:00', sub=None, xmp=e3.xmp_properties(captured='2026-03-01T12:00:10+09:00'))
        if k == 'tiff':
            kw['iptc'] = [(2, 55, '20260301'), (2, 60, '120010+0900')]
        path.write_bytes(t.full_time(k, **kw))
    run = run_document(loop, 'geotag', {'version': V, 'operation': 'geotagFromTrack', 'media': {'items': [{'id': 'g' + k, 'path': str(p)} for k, p in local.items()]}, 'tracks': [{'id': 'watch', 'path': str(track)}]})
    for k in local:
        data = bytes_of(loop, run, 'g' + k + EXT[k])
        assert abs(total(data, 'GPS', 4) - __import__('fractions').Fraction('10.001')) <= __import__('fractions').Fraction(2, 10 ** 10), k
    assert sha(EQUATOR) in json.dumps(loop.document(run, 'geotag-plan.json', '/trackSha256')), 'the captured GPX identity is part of the published plan'
    row('loop-geotag-from-track', 'geotagFromTrack', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    # copyMetadata: a JPEG master onto four containers
    dests = {k: media / ('d' + k + EXT[k]) for k in ('tiff', 'png', 'webp', 'heif')}
    for k, path in dests.items():
        path.write_bytes(t.full_time(k))
    run = run_document(loop, 'copy-metadata', {'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 'master', 'path': str(master)}] + [{'id': 'd' + k, 'path': str(p)} for k, p in dests.items()]},
                                                'source': {'item': 'master'}, 'transfer': {'groups': ['descriptive', 'camera']}, 'policies': {'existing': 'replace'}})
    for k in dests:
        snap = snapshot(bytes_of(loop, run, 'd' + k + EXT[k]), groups=['descriptive', 'camera'])
        assert (snap['title']['value']['text'], snap['keywords']['value'], snap['cameraMake']['value']) == ('Harbour', ['k1', 'k2'], 'Canon'), k
    row('loop-copy-metadata-containers', 'copyMetadata', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    # exportSidecar then applySidecar with the exported sidecars as the declared sources
    masters = []
    for i in range(3):
        path = media / ('m%d.jpg' % i)
        path.write_bytes(f4.master(seed=i + 1))
        masters.append({'id': 'm%d' % i, 'path': str(path)})
    run = run_document(loop, 'export-sidecar', {'version': V, 'operation': 'exportSidecar', 'media': {'items': masters}, 'transfer': {'groups': ['descriptive']}})
    sidecars = []
    for i in range(3):
        path = media / ('s%d.xmp' % i)
        path.write_bytes(bytes_of(loop, run, 'm%d.xmp' % i))
        sidecars.append(str(path))
    row('loop-export-sidecar-jpeg', 'exportSidecar', 'jpeg', True, verify(loop, run), outcome='succeeded', written=True)
    for k in ('tiff', 'png', 'webp'):
        (media / ('a' + k + EXT[k])).write_bytes(t.full_time(k))
    run = run_document(loop, 'apply-sidecar', {'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 'a' + k, 'path': str(media / ('a' + k + EXT[k])), 'sidecar': sc} for k, sc in zip(('tiff', 'png', 'webp'), sidecars)]},
                                                'source': {'sidecar': 'declared'}, 'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'replace'}})
    for k in ('tiff', 'png', 'webp'):
        snap = snapshot(bytes_of(loop, run, 'a' + k + EXT[k]), groups=['descriptive'])
        assert (snap['title']['value']['text'], snap['keywords']['value']) == ('Harbour', ['k1', 'k2']), k
    row('loop-apply-sidecar-containers', 'applySidecar', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    # exportSidecar from containers, planNames and organiseCopies with canonical extensions
    run = run_document(loop, 'export-sidecar-containers', {'version': V, 'operation': 'exportSidecar', 'media': items, 'transfer': {'groups': ['descriptive']}})
    for k in KINDS:
        assert b'>Harbour<' in bytes_of(loop, run, 'r%s.xmp' % k), k
    row('loop-export-sidecar-containers', 'exportSidecar', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    rule = {'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'itemId'}]}
    run = run_document(loop, 'plan-names', {'version': V, 'operation': 'planNames', 'media': items, **rule})
    assert [r['relativePath'] for r in loop.document(run, 'names-plan.json')['items']] == ['20260301_r%s%s' % (k, EXT[k]) for k in KINDS]
    row('loop-plan-names-containers', 'planNames', 'mixed', True, verify(loop, run), outcome='succeeded', written=False)
    run = run_document(loop, 'organise-copies', {'version': V, 'operation': 'organiseCopies', 'media': items, 'names': {**rule, 'extension': 'canonical'}})
    for k in KINDS:
        assert bytes_of(loop, run, '20260301_r%s%s' % (k, EXT[k])) == rich[k].read_bytes(), k
    row('loop-organise-copies-containers', 'organiseCopies', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    # minimise of a PNG and a WebP (AM-17) and the audit and compare reads
    png, webp = media / 'min.png', media / 'min.webp'
    png.write_bytes(t.png_g6())
    webp.write_bytes(f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.ck(b'EXIF', t.stream()), f.webp_xmp()))
    run = run_document(loop, 'minimise', {'version': V, 'operation': 'removeMetadata', 'media': {'items': [{'id': 'min_png', 'path': str(png)}, {'id': 'min_webp', 'path': str(webp)}]}, 'categories': ['minimise']})
    assert bytes_of(loop, run, 'min_webp.webp') == f.riff(f.ck(b'VP8 ', f.vp8()))
    out = bytes_of(loop, run, 'min_png.png')
    assert out.count(f.GAMA) == 1 and b'plain text' not in out and payloads(out).xmp[0] == 'absent'
    row('loop-minimise-png-webp', 'removeMetadata', 'mixed', True, verify(loop, run), outcome='succeeded', written=True)
    run = run_document(loop, 'audit', {'version': V, 'operation': 'auditMetadata', 'media': items, 'rules': ['requiredFields'], 'require': ['title', 'rightsUrl']})
    findings = loop.document(run, 'audit.json', '/findings')
    assert sorted((x['item'], x['field']) for x in findings) == sorted(('r' + k, 'rightsUrl') for k in KINDS), findings
    row('loop-audit-containers', 'auditMetadata', 'mixed', True, verify(loop, run), outcome='succeeded', written=False)
    run = run_document(loop, 'compare', {'version': V, 'operation': 'compareMetadata', 'media': items, 'baseline': 'rtiff', 'fields': ['cameraModel', 'title']})
    assert {r['outcome'] for r in loop.document(run, 'comparison.json', '/rows')} == {'same'}
    row('loop-compare-containers', 'compareMetadata', 'mixed', True, verify(loop, run), outcome='succeeded', written=False)


def part_a(root, config):
    photos = root / 'private' / 'photos'
    photos.mkdir(parents=True)
    for name, (data, _, _) in FILES.items():
        (photos / name).write_bytes(data)
    loop = Loop(root, config)

    def item(name): return {'items': [{'id': 'q', 'path': str(photos / name)}]}
    try:
        loop.call('methods')
        discovery(loop)
        loop.draft = loop.call('create_draft', provider='exiftool', name='container loop')
        loop.task = loop.call('create_task', objective='Inspect, edit and remove metadata of synthetic TIFF, DNG, PNG, WebP and HEIF files', allowed_providers=['exiftool'],
                              budget={'maxAttempts': 100, 'maxElapsedSeconds': 3400, 'timeoutPerStageSeconds': 300, 'maxRepeatedFailures': 10})
        for name in ('q.tif', 'q.dng', 'q.png', 'q.webp', 'q.heic'):
            data, container, protected = FILES[name]
            run = run_document(loop, 'edit-' + container, {'version': V, 'operation': 'editMetadata', 'media': item(name), 'edits': {'title': {'set': TITLE}, 'creator': {'set': [ARTIST]}}})
            out = bytes_of(loop, run, 'q' + Path(name).suffix)
            assert TITLE.encode() in out and (ARTIST.encode() + b'\0') in out, name
            for part in protected:
                assert out.count(part) == 1, (name, part[:12])
            row('loop-edit-' + container, 'editMetadata', container, True, verify(loop, run), outcome='succeeded', written=True)
        for name in ('q.tif', 'q.dng', 'q.png', 'q.webp'):
            data, container, protected = FILES[name]
            run = run_document(loop, 'remove-' + container, {'version': V, 'operation': 'removeMetadata', 'media': item(name), 'categories': ['descriptive', 'rights']})
            out = bytes_of(loop, run, 'q' + Path(name).suffix)
            for part in protected:
                assert out.count(part) == 1, (name, part[:12])
            assert b'Quarry gate' not in out and b'A. Mason\0' not in out, name
            row('loop-remove-' + container, 'removeMetadata', container, True, verify(loop, run), outcome='succeeded', written=True)
        run = run_document(loop, 'inspect-containers', {'version': V, 'operation': 'inspectMetadata', 'media': {'folder': {'path': str(photos), 'extensions': ['.tif', '.dng', '.png', '.webp', '.heic'], 'sidecars': 'none'}},
                                                         'profiles': ['rendering'], 'nativeListing': True})
        csv_text = bytes_of(loop, run, 'profile-rendering.csv').decode()
        for needle in ('"bare",\\N,"absent",64,"present",48,"present"',):
            assert needle in csv_text, csv_text
        row('loop-inspect-mixed-containers', 'inspectMetadata', 'mixed', True, verify(loop, run), outcome='succeeded', written=False)
        page = loop.call('inspect_resource', resource_id=run['resources']['metadata.json']['id'], pointer='/items', offset=0, limit=1, max_bytes=2048)
        assert page['mode'] == 'members' and page['page']['returned'] == 1, page
        family(loop, root, photos)
        # stale revision control
        stale_plan = loop.plan()
        loop.author({'version': V, 'operation': 'removeMetadata', 'media': item('q.png'), 'categories': ['location']})
        stale = loop.fault('STALE_REVISION', 'execute', plan_id=stale_plan['id'], expected_revision=stale_plan['revision'])
        # named refusals (never support): a HEIF without the items would need them created; HEIF removal is refused
        loop.author({'version': V, 'operation': 'editMetadata', 'media': item('bare.heic'), 'edits': {'title': {'set': TITLE}}})
        failed = loop.run('heif-creation-refusal', expect='failed')
        code = loop.call('observe', job_id=failed['job'], section='fault')['value']['code']
        assert code == 'NO_USABLE_ITEMS', code
        row('loop-edit-heif-item-creation-refused', 'editMetadata', 'heif', False, True, outcome='refused', kind='refusal', faultCode='HEIF_METADATA_ITEM_CREATION_UNSUPPORTED', written=False)
        loop.author({'version': V, 'operation': 'removeMetadata', 'media': item('q.heic'), 'categories': ['location']})
        failed = loop.run('heif-removal-refusal', expect='failed')
        assert loop.call('observe', job_id=failed['job'], section='fault')['value']['code'] == 'NO_USABLE_ITEMS'
        row('loop-remove-heif-refused', 'removeMetadata', 'heif', False, True, outcome='refused', kind='refusal', faultCode='HEIF_REMOVAL_UNSUPPORTED', written=False)
        loop.report['cases']['loop'] = {'staleExecute': stale['code'], 'runs': [r['label'] for r in loop.report['runs']]}
    finally:
        try:
            loop.client.close()
        except Exception as error:
            loop.report['closeNote'] = str(error)[:200]
    return loop.report


def part_b():
    import unittest
    import test_exiftool_e5_workflow as module
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.Chain)
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
    failed = {str(t).split('(')[0].strip() for t, _ in result.failures + result.errors}
    for key, (operation, note) in {'W1': ('correctTime', 'correct, plan and organise a mixed container set'), 'W2': ('applySidecar', 'export and apply sidecars to four containers'), 'W3': ('setLocation', 'locate and audit through the typed handoff'),
                                   'W4': ('removeMetadata', 'minimise and organise a share set')}.items():
        data = module.Chain.RESULTS.get(key)
        ok = data is not None and data.get('independentlyVerified', False) and not any('_' + key + '_' in name for name in failed)
        row('workflow-' + key, operation, 'mixed', ok, ok, outcome='succeeded' if ok else None, kind='workflow-chain', chainOperations=None if data is None else data['operation'], note=note, written=None)
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
        part = part_a(root, config)
        report['loop'] = {k: part[k] for k in ('cases', 'runs')}
        report['workflow'] = part_b()
        report['cases'] = ROWS
        report['verified'] = all(r['independentlyVerified'] for r in ROWS) and report['workflow']['wasSuccessful']
    finally:
        report['finishedAt'] = time.time()
        (root / 'acceptance.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: report.get(k) for k in ('verified',)}, indent=1))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
