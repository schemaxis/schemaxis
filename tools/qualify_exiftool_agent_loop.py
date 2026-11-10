#!/usr/bin/env python3
"""Public agent-service loop for the ExifTool metadata workbench read family, run against the real ExifTool 13.55 runtime.

A deterministic local client (not a language-model evaluation) drives ``python3 -m schemaxis agent``: discovery, context, authoring of valid and
invalid drafts, plan, execute, bounded paginated inspection of every published record, revision-bound verification and negative controls. Every
run uses a unique private fixture folder copied from the synthetic repository fixtures under the evidence directory, so no shared staging path
or lock is needed and nothing outside ``--output-directory`` is touched. Expected values are hand-written here from the fixture specification in
tools/author_exiftool_fixtures.py (never read back from ExifTool, the adaptor readers or its summaries).
Nothing here certifies photo provenance, capture time, location, authorship, privacy or exhaustive ExifTool behaviour, and the loop does not
qualify any other application. Native processes are started and reaped by the adaptor under its own process-group ownership and deadlines.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qualify_agent_service import Client  # noqa: E402
import qualify_exiftool_workbench as wb  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor as exiftool_adaptor, workbench as exiftool_workbench  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/exiftool'
V = 'schemaxis.exiftool/1'
WORKBENCH = ('ridge-line.jpg', 'quay-side.jpg', 'quay-side.xmp', 'sidecar-only.xmp')
FOUR = ('quay_side', 'ridge_line', 'sidecar_only')


def parse(lines): return list(csv.reader(io.StringIO('\n'.join(lines) + '\n')))


class Loop:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.client = Client(root / 'session', config=config)
        self.report = {'cases': {}, 'controls': {}, 'runs': []}
        self.draft = None
        self.task = None
        self.runs = {}

    # ---- thin helpers over the public methods
    def call(self, method, **params): return self.client.call(method, **params)

    def fault(self, code, method, location=None, **params):
        """A refused request: ``ok`` false with the exact fault code (and location when given)."""
        response = self.client.request(method, **params)
        assert not response['ok'], (method, 'was accepted but must be refused with ' + code)
        fault = response['fault']
        assert fault['code'] == code, (method, fault)
        if location is not None:
            assert fault['location'] == location, (method, fault)
        return fault

    def author(self, document, *, expect_valid=True):
        self.draft = self.call('edit_draft', document_id=self.draft['document'], expected_revision=self.draft['revision'], source=json.dumps(document, indent=2))
        assert self.draft['valid'] is expect_valid, self.draft['diagnostics']
        return self.draft

    def patch(self, edits):
        self.draft = self.call('patch_draft', document_id=self.draft['document'], expected_revision=self.draft['revision'], edits=edits)
        return self.draft

    def context(self, pointer, expand=True, **page):
        """One ``adaptor_context`` value by pointer: inline when it fits the response budget, otherwise assembled from its public members pages
        (a large registered qualification receipt makes ``/qualification`` a members page). A member too large to be inline is fetched by its own pointer
        when ``expand`` is set, else left as ``{'pointer', 'kind'}``. ``(value, mode, pages)``; no budget is raised."""
        first = self.call('adaptor_context', version=V, pointer=pointer, **page)
        if first['mode'] == 'value':
            return first['value'], 'value', 1
        assert first['mode'] == 'members', first
        stamp, offset, pages, members = first['revision'], 0, 0, []
        while offset is not None:
            part = first if offset == 0 else self.call('adaptor_context', version=V, pointer=pointer, offset=offset, revision=stamp, **page)
            assert part['container'] in ('object', 'array') and part['revision'] == stamp, part
            members += part['items']
            offset = part['page']['nextOffset']
            pages += 1
        values = [m['value'] if 'value' in m else self.context(m['pointer'], **page)[0] if expand else {'pointer': m['pointer'], 'kind': m['kind']} for m in members]
        return (dict(zip((m['key'] for m in members), values)) if first['container'] == 'object' else values), 'members', pages

    def source(self):
        data = self.call('draft', document_id=self.draft['document'], expected_revision=self.draft['revision'], length=16384)
        assert data['nextOffset'] is None
        return json.loads(data['source'])

    def plan(self):
        self.task = self.call('task', task_id=self.task['id'])
        return self.call('plan_draft', task_id=self.task['id'], expected_revision=self.task['revision'], document_id=self.draft['document'], draft_revision=self.draft['revision'])

    def run(self, label, *, expect='succeeded'):
        plan = self.plan()
        job = self.call('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        status = self.client.wait(job)
        assert status['status'] == expect, (label, status)
        record = {'label': label, 'job': job['id'], 'plan': plan['id'], 'planRevision': plan['revision'], 'draftRevision': self.draft['revision'], 'status': status['status']}
        if expect == 'succeeded':
            assert status['verified'] is True and status['nativeState'] == 'verified', status
            resources = self.call('observe', job_id=job['id'], section='resources')['value']
            record['resources'] = {r['name']: r for r in resources}
            self.runs[label] = record
        else:
            record['fault'] = self.call('observe', job_id=job['id'], section='fault')['value']
        self.report['runs'].append({k: v for k, v in record.items() if k != 'resources'} | ({'published': sorted(record['resources'])} if 'resources' in record else {}))
        return record

    # ---- bounded inspection of published records
    def rows(self, run, name, max_bytes=2048):
        """Every row of a published CSV, then each row again through one-row bounded pages at the table's revision: ``(columns, rows, pages)``."""
        resource = run['resources'][name]['id']
        columns = self.call('inspect_resource', resource_id=resource, pointer='/columns', max_bytes=max_bytes)['value']
        first = self.call('inspect_resource', resource_id=resource, pointer='/rows', limit=100, max_bytes=65536)
        stamp = first['revision']
        assert first['mode'] == 'value', 'a published table of this size is one bounded value'
        rows = first['value']
        pages = 1
        for offset in range(1, len(rows)):
            page = self.call('inspect_resource', resource_id=resource, pointer='/rows', offset=offset, limit=1, max_bytes=max_bytes, revision=stamp)
            assert page['mode'] == 'members' and page['page']['total'] == len(rows) and page['page']['returned'] == 1, page
            member = page['items'][0]
            value = member['value'] if 'value' in member else self.call('inspect_resource', resource_id=resource, pointer=member['pointer'], max_bytes=65536)['value']
            assert value == rows[offset], (name, offset)
            pages += 1
        return columns, rows, pages

    def document(self, run, name, pointer=''):
        return self.call('inspect_resource', resource_id=run['resources'][name]['id'], pointer=pointer, max_bytes=65536)['value']

    def all_bytes(self, run, name):
        resource = run['resources'][name]
        data, offset = b'', 0
        while offset is not None:
            part = self.call('resource', resource_id=resource['id'], offset=offset, length=16384)
            data += base64.b64decode(part['data'])
            offset = part['nextOffset']
        assert hashlib.sha256(data).hexdigest() == resource['sha256'] and len(data) == resource['bytes'], name
        return data

    def verify(self, run):
        value = self.call('verify', job_id=run['job'])['value']
        assert value['verified'] is True, value
        return value


def table_equal(columns, rows, literal):
    expected = parse(literal)
    assert columns == expected[0], (columns, expected[0])
    assert rows == expected[1:], (rows, expected[1:])


def copy_fixtures(directory, names):
    directory.mkdir(parents=True)
    for name in names:
        shutil.copyfile(FIXTURES / name, directory / name)
    return directory


def folder_document(path, profiles, **more):
    return {'version': V, 'operation': 'inspectMetadata', 'media': {'folder': {'path': str(path), **more}}, 'profiles': profiles}


OFFERED = ('inventoryPhotos', 'inspectMetadata', 'auditMetadata', 'compareMetadata', 'editMetadata', 'removeMetadata', 'reconcileTime', 'locate', 'correctTime', 'setLocation', 'geotagFromTrack')
QUALIFICATION_STATES = ('unknown', 'stale', 'source-current')


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
    expectations = (('photo folder metadata', 'operation/exiftool/inspectMetadata'), ('photo metadata', 'operation/exiftool/inspectMetadata'),
                    ('audit photos', 'operation/exiftool/auditMetadata'), ('audit photo metadata', 'operation/exiftool/auditMetadata'),
                    ('compare photos', 'operation/exiftool/compareMetadata'), ('compare EXIF of two photos', 'operation/exiftool/compareMetadata'),
                    # the write family is offered now: its queries find the real operations
                    ('edit photo metadata', 'operation/exiftool/editMetadata'), ('write photo metadata', 'operation/exiftool/editMetadata'),
                    ('set photo title', 'operation/exiftool/editMetadata'), ('write keywords to photos', 'operation/exiftool/editMetadata'),
                    ('strip location metadata from photos', 'operation/exiftool/removeMetadata'), ('strip photo metadata', 'operation/exiftool/removeMetadata'),
                    ('delete location from photos', 'operation/exiftool/removeMetadata'), ('minimise photo metadata', 'operation/exiftool/removeMetadata'),
                    # the time and location family is offered now: geotagging and time shifting find the real operations
                    ('geotag photos from a gpx track', 'operation/exiftool/geotagFromTrack'), ('shift capture time of photos', 'operation/exiftool/correctTime'),
                    ('fix photo timestamps', 'operation/exiftool/correctTime'), ('camera clock skew', 'operation/exiftool/reconcileTime'),
                    ('where was this photo taken', 'operation/exiftool/locate'), ('set photo location', 'operation/exiftool/setLocation'),
                    # the E4 naming plan is offered now: renaming (a naming plan for copies) finds the real operation
                    ('rename photos by capture date', 'operation/exiftool/planNames'))
    for query, wanted in expectations:
        found = search_all(loop, query)
        assert wanted in found, (query, found)
        shown[query] = found                  # every id of every page, never a prefix: a new operation may rank ahead of an older one without hiding it from the report
    # the first six operations of the adaptor (the E1 read family and the E2 edit and remove pair) stay in the COMPLETE 'photo metadata' result whatever newer operations rank ahead of them
    assert {'operation/exiftool/' + n for n in ('inventoryPhotos', 'inspectMetadata', 'auditMetadata', 'compareMetadata', 'editMetadata', 'removeMetadata')} <= set(shown['photo metadata']), shown['photo metadata']
    # operations that still do not exist in this adaptor must not be matched to it: raw native expressions and reverse geocoding
    for query in ('reverse geocode photos', 'run a raw exiftool expression'):
        found = search_all(loop, query)
        assert not [i for i in found if i.startswith('operation/exiftool/') and not i.endswith('/inventoryPhotos')], (query, found)
        shown[query] = found
    # observed, not asserted: discovery matches every query token, so a long natural sentence can find nothing
    for query in ('compare photo metadata against a baseline photo', 'write exif tags into a jpeg'):
        shown['(observed limit) ' + query] = search_all(loop, query)
    for name in OFFERED[4:]:
        assert loop.call('capabilities.describe', identity='operation/exiftool/' + name)['sections'], name
    context, materials_mode, _ = loop.context('/materials', max_bytes=65536)
    blob = json.dumps(context)
    for name in ('exiftool-inspect-baseline.json', 'exiftool-audit-baseline.json', 'exiftool-compare-baseline.json', 'exiftool-edit-baseline.json', 'exiftool-remove-baseline.json',
                 'exiftool-reconcile-time.json', 'exiftool-locate-baseline.json', 'exiftool-correct-time.json', 'exiftool-set-location.json', 'exiftool-geotag-track.json'):
        assert name in blob, ('adaptor context does not offer the example', name)
    # qualification: the scalar status pointer is always small; the whole scoped object is a value when unregistered and a public members page when a
    # large receipt is registered. Both are read through the public API with the default budget, must agree, and report the truthful state.
    status = loop.call('adaptor_context', version=V, pointer='/qualification/status')
    assert status['mode'] == 'value' and status['value'] in QUALIFICATION_STATES, status
    whole, whole_mode, whole_pages = loop.context('/qualification', expand=False)
    assert whole['status'] == status['value'] and isinstance(whole.get('scope') or whole.get('reason'), str), whole
    if status['value'] == 'unknown':
        assert whole['reason'], 'an unknown qualification state states why'
    else:
        assert set(whole) == {'status', 'receipt', 'scope'}, sorted(whole)
        receipt = {key: loop.call('adaptor_context', version=V, pointer='/qualification/receipt/' + key)['value'] for key in ('documentVersion', 'mode', 'verified')}
        assert receipt == {'documentVersion': V, 'mode': 'native', 'verified': True}, receipt
    contract = loop.call('capabilities.describe', identity='operation/exiftool/inspectMetadata')['sections']
    loop.report['cases']['discovery'] = {'queries': shown, 'contextMaterials': sorted(context), 'materialsMode': materials_mode, 'qualificationStatusReported': status['value'],
                                         'qualificationObjectMode': whole_mode, 'qualificationObjectPages': whole_pages, 'qualificationReceiptRegistered': 'receipt' in whole,
                                         'describeSections': sorted(contract)[:10]}


def invalid_drafts(loop, photos):
    base = folder_document(photos, ['capture'])
    cases = {}
    for label, change, code, location in (
            ('edit-operation-with-read-arguments', lambda d: d.update(operation='editMetadata'), 'UNKNOWN_ARGUMENT', '$'),
            ('remove-operation-with-read-arguments', lambda d: d.update(operation='removeMetadata'), 'UNKNOWN_ARGUMENT', '$'),
            ('edit-without-edits', lambda d: (d.update(operation='editMetadata'), d.pop('profiles')), 'MISSING_ARGUMENT', '$.arguments.edits'),
            ('remove-without-categories', lambda d: (d.update(operation='removeMetadata'), d.pop('profiles')), 'MISSING_ARGUMENT', '$.arguments.categories'),
            ('geotag-operation-with-read-arguments', lambda d: d.update(operation='geotagFromTrack'), 'UNKNOWN_ARGUMENT', '$'),
            ('unsupported-operation-rename', lambda d: d.update(operation='renamePhotos'), 'UNKNOWN_OPERATION', '$.operation'),
            ('native-geotag-option', lambda d: (d.update(operation='geotagFromTrack', geotag='/x/track.gpx'), d.pop('profiles')), 'UNKNOWN_ARGUMENT', '$'),
            ('time-shift-expression', lambda d: (d.update(operation='correctTime', shiftExpression='-AllDates+=1:0:0'), d.pop('profiles')), 'UNKNOWN_ARGUMENT', '$'),
            ('unknown-profile', lambda d: d.update(profiles=['nonsense']), 'INVALID_ARGUMENT', '$.arguments.profiles[0]'),
            ('unauthored-rename-argument', lambda d: d.update(renameTemplate='%Y%m%d'), 'UNKNOWN_ARGUMENT', '$'),
            ('raw-cli-argument', lambda d: d.update(exiftoolArguments=['-all=']), 'UNKNOWN_ARGUMENT', '$'),
            ('relative-folder', lambda d: d['media']['folder'].update(path='photos'), 'INVALID_PHOTO_SOURCE', '$.media.folder.path')):
        document = json.loads(json.dumps(base))
        change(document)
        draft = loop.author(document, expect_valid=False)
        diagnostic = draft['diagnostics'][0]
        assert diagnostic['code'] == code, (label, diagnostic)
        if location:
            assert diagnostic['location'] == location, (label, diagnostic)
        fault = loop.fault('INVALID_DRAFT', 'plan_draft', task_id=loop.task['id'], expected_revision=loop.call('task', task_id=loop.task['id'])['revision'], document_id=draft['document'], draft_revision=draft['revision'])
        assert fault['observed']['diagnostics'][0]['code'] == code
        cases[label] = {'code': diagnostic['code'], 'location': diagnostic['location']}
    loop.author(base)
    loop.report['controls']['invalidDrafts'] = cases


def time_location_loop(loop, photos):
    """The time and location operations through the public loop: real read runs over the workbench fixture folder (bounded inspection, revision-bound verification
    with a fresh native replay) and valid drafts and plans of the three write operations (their native writes are qualified by qualify_exiftool_time_location_loop.py)."""
    folder = {'folder': {'path': str(photos), 'extensions': ['.jpg'], 'depth': 1}}
    loop.author({'version': V, 'operation': 'reconcileTime', 'media': folder})
    run = loop.run('reconcile-time')
    assert sorted(run['resources']) == ['manifest.json', 'metadata.json', 'time-report.csv', 'time-report.json'], sorted(run['resources'])
    assert run['resources']['time-report.csv']['kind'] == 'table'
    report = loop.document(run, 'time-report.json')
    assert report['operation'] == 'reconcileTime' and report['report']['groups'], report.keys()
    assert all(g['state'] == 'insufficient' for g in report['report']['groups']), 'no reference was declared: every group must stay insufficient, never guessed'
    columns, rows, _ = loop.rows(run, 'time-report.csv')
    assert columns[:3] == ['item', 'group', 'groupState'], columns
    assert loop.verify(run)['nativeReplay'] == 'fresh-replay-matched'
    loop.author({'version': V, 'operation': 'locate', 'media': folder, 'compareTo': {'latitude': '12.568', 'longitude': '-45.6667', 'datum': 'WGS-84'}})
    run = loop.run('locate')
    assert sorted(run['resources']) == ['location-report.json', 'location.csv', 'manifest.json', 'metadata.json'], sorted(run['resources'])
    columns, rows, _ = loop.rows(run, 'location.csv')
    by = {r[0]: dict(zip(columns, r)) for r in rows}
    assert abs(float(by['ridge_line']['latitude']) - (12 + 34 / 60 + 5 / 3600)) < 1e-9 and abs(float(by['ridge_line']['longitude']) + (45 + 40 / 60)) < 1e-9, by['ridge_line']
    assert loop.verify(run)['nativeReplay'] == 'fresh-replay-matched'
    one = {'items': [{'id': 'ridge_line', 'path': str(photos / 'ridge-line.jpg')}]}
    (loop.root / 'private' / 'walk.gpx').write_text('<?xml version="1.0"?><gpx version="1.1" creator="synthetic" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
                                                     '<trkpt lat="0" lon="0"><time>2024-05-06T05:00:00Z</time></trkpt><trkpt lat="0" lon="0.001"><time>2024-05-06T05:01:00Z</time></trkpt></trkseg></trk></gpx>')
    drafts = {}
    for name, document in (('correctTime', {'version': V, 'operation': 'correctTime', 'media': one, 'corrections': [{'group': 'dev1', 'shift': {'hours': 1}}], 'apply': 'plan'}),
                           ('setLocation', {'version': V, 'operation': 'setLocation', 'media': one, 'default': {'latitude': '10.5', 'longitude': '20.25'}, 'apply': 'plan'}),
                           ('geotagFromTrack', {'version': V, 'operation': 'geotagFromTrack', 'media': one, 'tracks': [{'id': 'walk', 'path': str(loop.root / 'private' / 'walk.gpx')}], 'apply': 'plan'})):
        loop.author(document)
        plan = loop.plan()
        assert plan['id'] and plan['revision'] >= 1, plan
        drafts[name] = {'valid': True, 'planned': True}
    loop.report['cases']['timeLocation'] = {'readRuns': ['reconcile-time', 'locate'], 'drafts': drafts}


def baseline_inspect(loop, photos):
    loop.author(folder_document(photos, ['capture', 'device', 'location'], depth=1, sidecars='adjacent'))
    run = loop.run('inspect-baseline')
    assert sorted(run['resources']) == ['manifest.json', 'metadata.json', 'profile-capture.csv', 'profile-device.csv', 'profile-location.csv'], sorted(run['resources'])
    assert {r['kind'] for n, r in run['resources'].items() if n.endswith('.csv')} == {'table'}
    for name, literal in (('profile-capture.csv', wb.CAPTURE), ('profile-device.csv', wb.DEVICE)):
        columns, rows, pages = loop.rows(run, name)
        table_equal(columns, rows, literal)
        assert pages >= 3, 'rows must have been paged one at a time'
    columns, rows, _ = loop.rows(run, 'profile-location.csv')
    assert ','.join('"%s"' % c for c in columns) == wb.LOCATION_HEADER
    by = {r[0]: dict(zip(columns, r)) for r in rows}
    assert list(by) == list(FOUR)
    ridge = by['ridge_line']
    assert abs(float(ridge['gpsLatitude']) - (12 + 34 / 60 + 5 / 3600)) < 1e-12 and abs(float(ridge['gpsLongitude']) + (45 + 40 / 60)) < 1e-12
    assert (ridge['gpsAltitude'], ridge['gpsDirection'], ridge['gpsDirectionReference'], ridge['gpsDatum'], ridge['gpsUtc'], ridge['locationCity'], ridge['locationCountry']) == \
        ('123.4', '90.5', 'true', 'WGS-84', '2024-05-06T05:08:09Z', 'Imaginary Town', 'Nowhereland')
    assert all(v == 'absent' for k, v in by['quay_side'].items() if k.endswith('State'))
    assert [by['sidecar_only'][k] for k in ('gpsLatitudeState', 'gpsUtcState', 'locationCityState')] == ['unsupported', 'unsupported', 'absent']
    manifest = loop.document(run, 'manifest.json')
    assert manifest['status'] == 'complete' and manifest['counts'] == {'scanned': 5, 'items': 3, 'succeeded': 3, 'faulted': 0, 'excluded': 1, 'excludedForLimitOrSafety': 0}, manifest['counts']
    assert [(e['path'], e['role'], e.get('reason')) for e in manifest['entries']] == [('notes.txt', 'excluded', 'extension'), ('quay-side.jpg', 'item', None), ('quay-side.xmp', 'sidecar', 'sidecar-of:quay_side'), ('ridge-line.jpg', 'item', None), ('sidecar-only.xmp', 'item', None)]
    for entry in manifest['entries'][1:]:
        assert entry['sha256'] == hashlib.sha256((FIXTURES / entry['path']).read_bytes()).hexdigest(), entry['path']
    metadata = loop.document(run, 'metadata.json')
    assert metadata['setStatus'] == 'complete' and metadata['review']['privacyCertified'] is False and metadata['review']['captureTimeCertified'] is False and metadata['losses']
    assert [i['id'] for i in metadata['items']] == list(FOUR)
    assert str(photos) not in json.dumps(metadata) + json.dumps(manifest), 'private folder path leaked into a publication'
    # every published record is readable as exact bounded bytes and equals the digest the verified publication declares
    sizes = {name: len(loop.all_bytes(run, name)) for name in run['resources']}
    meta = loop.call('inspect_resource_metadata', resource_id=run['resources']['manifest.json']['id'], max_bytes=65536)
    assert meta['value'], 'publication metadata companion'
    verified = loop.verify(run)
    assert verified['nativeListing'] is False and verified['proofLevels'] == ['independent'] and verified['setStatus'] == 'complete' and verified['succeeded'] == 3
    loop.report['cases']['inspect-baseline'] = {'items': 3, 'tablesLiteral': ['capture', 'device', 'location'], 'publishedBytes': sizes, 'verified': True, 'pagedOneRowPerPage': True}
    return run


def edit_to_native_listing(loop, photos):
    loop.patch([{'op': 'add', 'path': '/nativeListing', 'value': True}, {'op': 'add', 'path': '/profiles/-', 'value': 'description'}])
    document = loop.source()
    assert document['nativeListing'] is True and document['profiles'] == ['capture', 'device', 'location', 'description'], document
    run = loop.run('inspect-native')
    assert 'native-observations.json' in run['resources'] and 'profile-description.csv' in run['resources']
    columns, rows, _ = loop.rows(run, 'profile-description.csv')
    by = {r[0]: dict(zip(columns, r)) for r in rows}
    assert by['ridge_line']['description'] == 'Ridge line at dusk' and by['ridge_line']['title'] == 'Ridge' and by['ridge_line']['descriptionState'] == 'present'
    assert by['quay_side']['description'] == 'Quay at noon' and by['sidecar_only']['description'] == 'Described only in a sidecar'
    observed = loop.document(run, 'native-observations.json')
    assert observed['proofLevel'] == 'native-observed' and [i['id'] for i in observed['items']] == ['quay_side', 'ridge_line', 'sidecar_only']
    ridge = {(o['group0'], o['group1'], o['name'], o['instance']): o['value'] for o in observed['items'][1]['files'][0]['observations']}
    assert ridge[('EXIF', 'IFD0', 'Make', 0)] == 'Northfield' and ridge[('IPTC', 'IPTC', 'City', 0)] == 'Imaginary Town' and ridge[('EXIF', 'GPS', 'GPSMapDatum', 0)] == 'WGS-84'
    assert not any(g == 'System' for g, *_ in ridge)
    verified = loop.verify(run)
    assert verified['nativeListing'] is True and verified['nativeReplay'] == 'fresh-replay-matched' and verified['proofLevels'] == ['independent', 'native-observed'], verified
    pages = []
    offset = 0
    first = loop.call('inspect_resource', resource_id=run['resources']['native-observations.json']['id'], pointer='/items/1/files/0/observations', limit=5, max_bytes=2048)
    assert first['mode'] == 'members' and first['page']['total'] > 20, first['page']
    stamp = first['revision']
    while offset is not None:
        page = loop.call('inspect_resource', resource_id=run['resources']['native-observations.json']['id'], pointer='/items/1/files/0/observations', offset=offset, limit=5, max_bytes=2048, revision=stamp)
        pages.append(page['page']['returned'])
        offset = page['page']['nextOffset']
    assert sum(pages) == first['page']['total']
    # a resource read against a wrong evidence revision is refused with the exact fault
    stale = loop.fault('STALE_OBSERVATION', 'inspect_resource', resource_id=run['resources']['native-observations.json']['id'], pointer='/items/1/files/0/observations', offset=5, limit=5, max_bytes=2048, revision='sha256:' + '0' * 64)
    loop.report['cases']['inspect-native'] = {'verifiedNativeReplay': True, 'observationPages': len(pages), 'observations': first['page']['total'], 'staleObservation': stale['code']}
    return run


def present_fields_control(loop):
    """Fields no other fixture records (modify time, lens make and serial): a present value decodes, agrees with ExifTool, and never stands in for capture time."""
    copy = copy_fixtures(loop.root / 'private' / 'lens', ('lens-record.jpg',))
    loop.author({'version': V, 'operation': 'inspectMetadata', 'media': {'items': [{'id': 'lens_record', 'path': str(copy / 'lens-record.jpg')}]}, 'profiles': ['capture', 'device'], 'nativeListing': True})
    run = loop.run('inspect-lens-record')
    columns, rows, _ = loop.rows(run, 'profile-capture.csv')
    capture = dict(zip(columns, rows[0]))
    assert (capture['modifiedLocal'], capture['modifiedLocalState'], capture['capturedLocal'], capture['capturedLocalState']) == ('2024-05-06T08:00:00', 'present', wb.N, 'absent'), capture
    columns, rows, _ = loop.rows(run, 'profile-device.csv')
    device = dict(zip(columns, rows[0]))
    assert [device[k] for k in ('cameraMake', 'cameraModel', 'lensMake', 'lensModel', 'lensSerialNumber', 'bodySerialNumber')] == ['Northfield', 'NF-300', 'Northfield Optics', 'NF 85mm f/1.4', 'LS-0042', wb.N], device
    assert device['lensSerialNumberState'] == 'present' and device['bodySerialNumberState'] == 'absent'
    verified = loop.verify(run)
    assert verified['nativeReplay'] == 'fresh-replay-matched'
    loop.report['cases']['present-fields'] = {'modifiedLocal': 'present, not capture time', 'lensMake': 'present', 'lensSerialNumber': 'present', 'nativeReplay': verified['nativeReplay']}


def stale_and_revision_controls(loop, photos):
    base = loop.source()
    plan = loop.plan()
    edited = loop.author({**base, 'profiles': ['capture']})
    stale = loop.fault('STALE_REVISION', 'execute', plan_id=plan['id'], expected_revision=plan['revision'])
    loop.fault('STALE_REVISION', 'edit_draft', document_id=edited['document'], expected_revision=edited['revision'] - 1, source='{}')
    current = loop.plan()
    loop.fault('STALE_REVISION', 'execute', plan_id=current['id'], expected_revision=current['revision'] + 5)
    loop.fault('STALE_REVISION', 'plan_draft', task_id=loop.task['id'], expected_revision=loop.task['revision'] - 1, document_id=edited['document'], draft_revision=edited['revision'])
    loop.report['controls']['staleAndRevision'] = {'planAfterDraftChange': stale['code'], 'wrongDraftRevision': 'STALE_REVISION', 'wrongTaskRevision': 'STALE_REVISION', 'wrongExecuteRevision': 'STALE_REVISION'}


def audit_loop(loop, photos):
    document = json.loads((ROOT / 'examples/schemaxis/exiftool-audit-baseline.json').read_text())
    document['media']['folder']['path'] = str(photos)
    loop.author(document)
    run = loop.run('audit-baseline')
    audit = loop.document(run, 'audit.json')
    got = {(f['rule'], f['item'], f['field'], f['status']) for f in audit['findings']}
    assert got == wb.AUDIT, got ^ wb.AUDIT
    assert audit['summary']['itemsAudited'] == 3 and audit['summary']['itemsFaulted'] == 0
    columns, rows, _ = loop.rows(run, 'findings.csv')
    # hand-derived: quay-side records a make and model (device identity); ridge-line a GPS position, a body serial and an artist; the sidecar-only item a creator
    assert columns == ['item', 'rule', 'severity', 'field', 'status', 'message'] and rows == [
        ['quay_side', 'requiredFields', 'warning', 'capturedLocal', 'absent', 'Capture time (local wall time) is required but is absent'],
        ['quay_side', 'privacyInventory', 'info', wb.N, 'present', 'the file records device-identity metadata'],
        ['ridge_line', 'privacyInventory', 'info', wb.N, 'present', 'the file records location metadata'],
        ['ridge_line', 'privacyInventory', 'info', wb.N, 'present', 'the file records device-identity metadata'],
        ['ridge_line', 'privacyInventory', 'info', wb.N, 'present', 'the file records personal-identity metadata'],
        ['sidecar_only', 'requiredFields', 'warning', 'cameraModel', 'absent', 'Camera model is required but is absent'],
        ['sidecar_only', 'privacyInventory', 'info', wb.N, 'present', 'the file records personal-identity metadata']], rows
    loop.verify(run)
    # meaningful edit 1: require one more field -> exactly two additional literal findings (hand-derived from the fixtures: neither quay-side nor the sidecar-only item records a copyright)
    loop.patch([{'op': 'add', 'path': '/require/-', 'value': 'copyright'}])
    run = loop.run('audit-require-copyright')
    got = {(f['rule'], f['item'], f['field'], f['status']) for f in loop.document(run, 'audit.json')['findings']}
    assert got == wb.AUDIT | {('requiredFields', 'quay_side', 'copyright', 'absent'), ('requiredFields', 'sidecar_only', 'copyright', 'absent')}, got ^ wb.AUDIT
    # invalid combination: a required field without the rule that uses it
    source = loop.source()
    narrowed = json.loads(json.dumps(source))
    narrowed['rules'] = ['sourceConflicts']
    loop.author(narrowed, expect_valid=False)
    diagnostic = loop.draft['diagnostics'][0]
    assert diagnostic['code'] == 'INVALID_AUDIT' and diagnostic['location'] == '$.require', diagnostic
    # meaningful edit 2: conflicts only, over explicit items (conflict-desk disagrees with itself between EXIF, IPTC and XMP)
    copy = copy_fixtures(loop.root / 'private' / 'conflicts', ('conflict-desk.jpg', 'ridge-line.jpg', 'harbour-light.jpg'))
    explicit = {'version': V, 'operation': 'auditMetadata', 'media': {'items': [{'id': 'conflict_desk', 'path': str(copy / 'conflict-desk.jpg')}, {'id': 'ridge_line', 'path': str(copy / 'ridge-line.jpg')}]},
                'profiles': ['description', 'capture', 'rights'], 'rules': ['sourceConflicts']}
    loop.author(explicit)
    run = loop.run('audit-conflicts-items')
    findings = loop.document(run, 'audit.json')['findings']
    assert findings and {f['rule'] for f in findings} == {'sourceConflicts'} and {f['item'] for f in findings} == {'conflict_desk'}, findings
    fields = {f['field'] for f in findings}
    assert {'description', 'creator', 'capturedLocal'} <= fields, fields  # EXIF, IPTC and XMP disagree on the description and creator, and XMP's time is one second after EXIF's
    loop.report['cases']['audit'] = {'baselineLiteral': True, 'requireEdit': 'copyright adds two literal findings', 'narrowedRulesInvalid': diagnostic['code'] + ' ' + diagnostic['location'], 'conflictFields': sorted(fields)}
    return copy


def compare_loop(loop, copy):
    items = [{'id': i, 'path': str(copy / f)} for i, f in (('ridge_line', 'ridge-line.jpg'), ('conflict_desk', 'conflict-desk.jpg'))]
    dup = copy_fixtures(loop.root / 'private' / 'dups', ('duplicate-tags.jpg',))
    items.append({'id': 'duplicate_tags', 'path': str(dup / 'duplicate-tags.jpg')})
    document = {'version': V, 'operation': 'compareMetadata', 'media': {'items': items}, 'baseline': 'ridge_line', 'profiles': ['device', 'description']}
    loop.author(document)
    run = loop.run('compare-ridge')
    rows = loop.document(run, 'comparison.json')['rows']
    assert {(r['item'], r['field']): r['outcome'] for r in rows} == {(i, f): o for i, m in wb.OUTCOMES.items() for f, o in m.items()}
    columns, differences, _ = loop.rows(run, 'differences.csv')
    assert len(differences) == 22 and differences[0][:5] == ['conflict_desk', 'cameraMake', 'different', 'present', 'present'] and differences[0][5:] == ['Northfield', 'Riverside Optics']
    # meaningful edit: baseline a different item. Hand-derived from the fixtures: the baseline has two camera makes in one IFD (ambiguous) and only the model 'Twin'.
    loop.patch([{'op': 'replace', 'path': '/baseline', 'value': 'duplicate_tags'}])
    run = loop.run('compare-duplicate-baseline')
    outcomes = {(r['item'], r['field']): r['outcome'] for r in loop.document(run, 'comparison.json')['rows']}
    expected = {('ridge_line', f): o for f, o in {'cameraMake': 'not-comparable', 'cameraModel': 'different', 'software': 'missing-in-baseline', 'lensMake': 'both-absent', 'lensModel': 'missing-in-baseline',
                                                  'bodySerialNumber': 'missing-in-baseline', 'lensSerialNumber': 'both-absent', 'title': 'missing-in-baseline', 'description': 'missing-in-baseline',
                                                  'keywords': 'missing-in-baseline', 'rating': 'missing-in-baseline'}.items()}
    expected |= {('conflict_desk', f): o for f, o in {'cameraMake': 'not-comparable', 'cameraModel': 'different', 'software': 'both-absent', 'lensMake': 'both-absent', 'lensModel': 'both-absent',
                                                      'bodySerialNumber': 'both-absent', 'lensSerialNumber': 'both-absent', 'title': 'both-absent', 'description': 'not-comparable',
                                                      'keywords': 'both-absent', 'rating': 'both-absent'}.items()}
    assert outcomes == expected, {k: (outcomes.get(k), expected.get(k)) for k in set(outcomes) | set(expected) if outcomes.get(k) != expected.get(k)}
    # a baseline that is not an authored item is refused when the draft is edited; a baseline whose own item cannot be read fails the run as a structural fault
    planned = loop.fault('INVALID_BASELINE', 'patch_draft', '$.baseline', document_id=loop.draft['document'], expected_revision=loop.draft['revision'], edits=[{'op': 'replace', 'path': '/baseline', 'value': 'absent_item'}])
    broken = loop.root / 'private' / 'dups' / 'broken.jpg'
    broken.write_bytes(b'this is not a jpeg')
    loop.patch([{'op': 'add', 'path': '/media/items/-', 'value': {'id': 'broken', 'path': str(broken)}}, {'op': 'replace', 'path': '/baseline', 'value': 'broken'}])
    loop.run('compare-faulted-baseline', expect='failed')
    fault = loop.report['runs'][-1]['fault']
    assert fault['code'] == 'INVALID_BASELINE' and fault['location'] == '$.baseline' and fault['observed']['value'] == 'broken', fault
    loop.report['cases']['compare'] = {'baselineRidge': 'literal 22 outcomes', 'baselineDuplicateTags': 'literal 22 outcomes', 'unauthoredBaseline': planned['code'] + ' ' + planned['location'], 'faultedBaseline': fault['code'] + ' ' + fault['location']}


def folder_selection(loop):
    tree = loop.root / 'private' / 'tree'
    copy_fixtures(tree, WORKBENCH + ('conflict-desk.jpg',))
    (tree / 'notes.txt').write_bytes(b'not metadata')
    (tree / '.hidden.jpg').write_bytes((FIXTURES / 'ridge-line.jpg').read_bytes())
    (tree / 'sub').mkdir()
    shutil.copyfile(FIXTURES / 'orchard-gate.jpg', tree / 'sub' / 'orchard-gate.jpg')
    (tree / 'sub' / 'deep').mkdir()
    shutil.copyfile(FIXTURES / 'harbour-light.jpg', tree / 'sub' / 'deep' / 'harbour-light.jpg')
    (tree / 'broken.jpg').write_bytes(b'this is not a jpeg')
    os.symlink('ridge-line.jpg', tree / 'link.jpg')

    def manifest_of(label, document):
        loop.author(document)
        run = loop.run(label)
        return loop.document(run, 'manifest.json'), run
    base = folder_document(tree, ['capture'], extensions=['.jpg'], depth=0)
    manifest, run = manifest_of('tree-depth0', base)
    reasons = {e['path']: (e['role'], e.get('reason'), e.get('status')) for e in manifest['entries']}
    assert reasons == {'.hidden.jpg': ('excluded', 'hidden', None), 'broken.jpg': ('item', None, 'fault'), 'conflict-desk.jpg': ('item', None, 'ok'), 'link.jpg': ('excluded', 'symlink', None),
                       'notes.txt': ('excluded', 'extension', None), 'quay-side.jpg': ('item', None, 'ok'), 'quay-side.xmp': ('sidecar', 'sidecar-of:quay_side', None),
                       'ridge-line.jpg': ('item', None, 'ok'), 'sidecar-only.xmp': ('excluded', 'extension', None), 'sub': ('excluded', 'directory-beyond-depth', None)}, reasons
    assert manifest['status'] == 'partial' and [e['path'] for e in manifest['entries']] == sorted([e['path'] for e in manifest['entries']], key=os.fsencode)
    columns, rows, _ = loop.rows(run, 'profile-capture.csv')
    assert [r[0] for r in rows] == ['conflict_desk', 'quay_side', 'ridge_line'], 'only usable items become rows, in byte-order of their paths'
    metadata = loop.document(run, 'metadata.json')
    assert metadata['setStatus'] == 'partial' and {i['id']: i['status'] for i in metadata['items']} == {'broken': 'fault', 'conflict_desk': 'ok', 'quay_side': 'ok', 'ridge_line': 'ok'}
    broken = next(i for i in metadata['items'] if i['id'] == 'broken')
    assert broken['fault']['code'] == 'UNSUPPORTED_MEDIA', broken['fault']
    loop.verify(run)
    # depth 1 reaches one directory level; depth 2 reaches the second
    shown = {}
    for depth, wanted in ((1, {'sub/orchard-gate.jpg': 'item', 'sub/deep': 'directory-beyond-depth'}), (2, {'sub/orchard-gate.jpg': 'item', 'sub/deep': 'directory-scanned', 'sub/deep/harbour-light.jpg': 'item'})):
        manifest, run = manifest_of('tree-depth%d' % depth, {**base, 'media': {'folder': {**base['media']['folder'], 'depth': depth}}})
        got = {e['path']: (e.get('reason') if e['role'] == 'excluded' else e['role']) for e in manifest['entries'] if e['path'].startswith('sub')}
        assert got == {'sub': 'directory-scanned', **wanted}, got
        shown[depth] = got
    # count limit: the first usable item in byte order of its relative path ('deep/...' before 'orchard-gate.jpg') is kept, the rest are excluded with a reason that makes the set partial
    manifest, run = manifest_of('tree-limit', folder_document(tree / 'sub', ['capture'], maxItems=1, depth=2))
    assert [(e['path'], e['role'], e.get('reason')) for e in manifest['entries']] == [('deep', 'excluded', 'directory-scanned'), ('deep/harbour-light.jpg', 'item', None), ('orchard-gate.jpg', 'excluded', 'count-limit')], manifest['entries']
    assert manifest['status'] == 'partial' and manifest['counts']['excludedForLimitOrSafety'] == 1
    # every entry unusable: structural fault, no publication
    bad = loop.root / 'private' / 'allbad'
    bad.mkdir()
    (bad / 'one.jpg').write_bytes(b'not a jpeg')
    (bad / 'two.jpg').write_bytes(b'\xff\xd8\xff\xd9')
    loop.author(folder_document(bad, ['capture']))
    record = loop.run('all-bad', expect='failed')
    fault = record['fault']
    assert fault['code'] == 'NO_USABLE_ITEMS' and fault['location'] == '$.media', fault
    assert loop.call('observe', job_id=record['job'], section='resources')['value'] == []
    loop.fault('EVIDENCE_UNAVAILABLE', 'observe', job_id=record['job'], section='verification')
    loop.report['cases']['folder-selection'] = {'depth0': 'literal manifest', 'depthLevels': {str(k): v for k, v in shown.items()}, 'countLimit': 'partial with count-limit exclusion', 'allFaulted': fault['code'] + ' ' + fault['location']}


def folder_change_control(loop, exe):
    """Run-level MEDIA_FOLDER_CHANGED with the real configured ExifTool path: the folder is changed at a deliberate owned boundary (a wrapper around the host's
    capture step, after the first item was captured), never by timing and never inside a native process. The fault must precede every native stage."""
    shown = {}
    for label, mutate, changed in (
            ('matching-file-added', lambda root: shutil.copyfile(FIXTURES / 'harbour-light.jpg', root / 'harbour-light.jpg'), ['harbour-light.jpg']),
            ('later-file-bytes-changed-same-path', lambda root: shutil.copyfile(FIXTURES / 'orchard-gate.jpg', root / 'ridge-line.jpg'), ['ridge-line.jpg'])):
        root = copy_fixtures(loop.root / 'private' / ('changing-' + label), ('quay-side.jpg', 'ridge-line.jpg'))
        out = loop.root / 'private' / ('changing-' + label + '-out')
        document = folder_document(root, ['capture'], depth=0, sidecars='none')
        original, seen = exiftool_workbench.capture_target, []

        def boundary(plan, order, target, *rest):
            outcome = original(plan, order, target, *rest)
            seen.append(target['id'])
            if len(seen) == 1:
                mutate(root)
            return outcome
        exiftool_workbench.capture_target = boundary
        try:
            try:
                exiftool_adaptor.run(document, out, executable=str(exe), timeout=120)
                raise AssertionError('a folder that changed during capture must fail the run')
            except SchemaxisError as error:
                fault = error.fault
        finally:
            exiftool_workbench.capture_target = original
        assert (fault.code, fault.location) == ('MEDIA_FOLDER_CHANGED', '$.media.folder.path') and fault.observed['changed'] == changed, fault.to_dict()
        result = json.loads((out / 'result.json').read_text())
        assert result['status'] == 'failed' and result['verified'] is False and result['fault']['code'] == 'MEDIA_FOLDER_CHANGED', result
        assert sorted(path.name for path in out.iterdir()) == ['authored.json', 'captured', 'plan.json', 'result.json'], 'a native stage, capture record or publication exists'
        shown[label] = {'fault': fault.code, 'location': fault.location, 'changed': fault.observed['changed'], 'files': sorted(path.name for path in out.iterdir()), 'nativeStagesStarted': 0}
    loop.report['controls']['folderChangedDuringCapture'] = shown


def no_runtime_control(loop, native_run, plain_run):
    """A second agent without a configured ExifTool: the independent publication verifies, the native listing is never reported verified."""
    loop.client.close()
    empty = loop.root / 'config-no-exiftool.json'
    empty.write_text(json.dumps({'version': 1, 'locations': {}}))
    saved = os.environ.pop('SCHEMAXIS_EXIFTOOL', None)
    client = Client(loop.root / 'session', config=empty)
    try:
        plain = client.call('verify', job_id=plain_run['job'])['value']
        assert plain['verified'] is True and plain['nativeReplay'].startswith('not-replayed'), plain
        response = client.request('verify', job_id=native_run['job'])
        assert not response['ok'] and response['fault']['code'] == 'NATIVE_REPLAY_UNAVAILABLE' and response['fault']['location'] == '$.runtime.exiftool', response
        assert response['fault']['observed']['independentVerified'] is True and response['fault']['observed']['nativeVerified'] is False
        status = client.call('job', job_id=native_run['job'])
        assert status['status'] == 'failed' and status['verified'] is False and status['faultCode'] == 'NATIVE_REPLAY_UNAVAILABLE', status
        loop.report['controls']['noConfiguredRuntime'] = {'independentOnlyRun': 'verified, nativeReplay not-replayed', 'nativeListingRun': response['fault']['code'] + ' ' + response['fault']['location'], 'jobInvalidated': status['status']}
    finally:
        client.close()
        if saved is not None:
            os.environ['SCHEMAXIS_EXIFTOOL'] = saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exiftool', type=Path)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--discovery-only', action='store_true', help='run only the public discovery/context cases, which need no native runtime (not a qualification)')
    args = parser.parse_args()
    if args.exiftool is None and not args.discovery_only:
        parser.error('--exiftool is required unless --discovery-only')
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ.pop('SCHEMAXIS_EXIFTOOL', None)
    config = root / 'config.json'
    config.write_text(json.dumps({'version': 1, 'locations': {} if args.discovery_only else {'exiftool': str(args.exiftool.resolve())}}))
    if args.discovery_only:
        loop = Loop(root, config)
        try:
            discovery(loop)
            loop.report['verified'] = True
        finally:
            loop.client.close()
            (root / 'acceptance-discovery.json').write_text(json.dumps({'scope': 'discovery and context only, no native runtime; not a qualification', **loop.report}, indent=2, ensure_ascii=False))
        print(json.dumps(loop.report['cases']['discovery']['qualificationStatusReported']), loop.report['cases']['discovery']['qualificationObjectMode'])
        return
    photos = copy_fixtures(root / 'private' / 'photos', WORKBENCH)
    (photos / 'notes.txt').write_bytes(b'not metadata')
    loop = Loop(root, config)
    report = loop.report
    report.update(scope=__doc__.split('\n\n')[0], verified=False, startedAt=time.time(), runtime={'script': args.exiftool.name, 'sha256': hashlib.sha256(args.exiftool.read_bytes()).hexdigest()})
    try:
        loop.call('methods')
        discovery(loop)
        loop.draft = loop.call('create_draft', provider='exiftool', name='workbench loop')
        loop.task = loop.call('create_task', objective='Inspect, audit and compare synthetic photo metadata', allowed_providers=['exiftool'], budget={'maxAttempts': 60, 'maxElapsedSeconds': 1500, 'timeoutPerStageSeconds': 300, 'maxRepeatedFailures': 10})
        invalid_drafts(loop, photos)
        time_location_loop(loop, photos)
        plain = baseline_inspect(loop, photos)
        native = edit_to_native_listing(loop, photos)
        present_fields_control(loop)
        stale_and_revision_controls(loop, photos)
        copy = audit_loop(loop, photos)
        compare_loop(loop, copy)
        folder_selection(loop)
        folder_change_control(loop, args.exiftool.resolve())
        no_runtime_control(loop, native, plain)
        report['verified'] = True
    finally:
        report['finishedAt'] = time.time()
        try:
            loop.client.close()
        except Exception as error:  # the no-runtime control closes the first client; a second close is harmless
            report['closeNote'] = str(error)[:200]
        (root / 'acceptance.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ('verified', 'runs')}, indent=1, ensure_ascii=False)[:4000])


if __name__ == '__main__':
    main()
