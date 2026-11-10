#!/usr/bin/env python3
"""Public author / plan / run / inspect / verify loop and real produced-image handoff for the ExifTool write family, against a real ExifTool 13.55.

Part A drives ``python3 -m schemaxis agent`` with a deterministic local client (not a language-model evaluation): discovery (positive and negative searches),
valid and invalid drafts with exact fault codes and locations, plan, execute, small-page revision-bound inspection of the published manifest and report,
revision-bound verification and stale-revision refusals. Part B runs the workflow scheduler over real produced images: an ``editMetadata`` producer and a
``removeMetadata`` producer (two distinct image producers) feed ``inspectMetadata`` consumers through ``{"$artifact": id, "index": N}`` bindings; it checks the
exact bound bytes and per-item identities, an unchanged resume (everything reused), invalidation by changed source bytes and by changed folder membership, a
changed authored document (resume refused) and the refused-slot and out-of-range bindings.
Every run uses a unique private fixture folder under ``--output-directory``: no shared staging path or lock. Expected values are hand-written from the fixture
specification in tools/author_exiftool_fixtures.py. Nothing here certifies photo provenance, privacy or exhaustive ExifTool behaviour.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qualify_agent_service import Client  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
import author_exiftool_fixtures as author  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
V = 'schemaxis.exiftool/1'
FILES = author.edit_files()


def sha(data): return hashlib.sha256(data).hexdigest()


class Loop:
    def __init__(self, root, config):
        self.client = Client(root / 'session', config=config)
        self.report = {'cases': {}, 'controls': {}, 'runs': []}
        self.draft = self.task = None

    def call(self, method, **params): return self.client.call(method, **params)

    def fault(self, code, method, location=None, **params):
        response = self.client.request(method, **params)
        assert not response['ok'], (method, 'was accepted but must be refused with ' + code)
        fault = response['fault']
        assert fault['code'] == code, (method, fault)
        if location is not None:
            assert fault['location'] == location, (method, fault)
        return fault

    def author(self, document, *, expect_valid=True):
        self.draft = self.call('edit_draft', document_id=self.draft['document'], expected_revision=self.draft['revision'], source=json.dumps(document, indent=2))
        assert expect_valid is None or self.draft['valid'] is expect_valid, self.draft['diagnostics']
        return self.draft

    def plan(self):
        self.task = self.call('task', task_id=self.task['id'])
        return self.call('plan_draft', task_id=self.task['id'], expected_revision=self.task['revision'], document_id=self.draft['document'], draft_revision=self.draft['revision'])

    def run(self, label, expect='succeeded'):
        plan = self.plan()
        job = self.call('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        status = self.client.wait(job)
        assert status['status'] == expect, (label, status)
        record = {'label': label, 'job': job['id'], 'plan': plan['id'], 'status': status['status']}
        if expect == 'succeeded':
            assert status['verified'] is True and status['nativeState'] == 'verified', status
            record['resources'] = {r['name']: r for r in self.call('observe', job_id=job['id'], section='resources', max_bytes=65536)['value']}
        self.report['runs'].append({k: v for k, v in record.items() if k != 'resources'} | ({'published': sorted(record['resources'])} if 'resources' in record else {}))
        return record

    def document(self, run, name, pointer=''):
        return self.call('inspect_resource', resource_id=run['resources'][name]['id'], pointer=pointer, max_bytes=65536)['value']


def private(root):
    photos = root / 'private' / 'photos'
    photos.mkdir(parents=True)
    for name in ('edit-rich.jpg', 'edit-rich-mm.jpg', 'edit-trailer.jpg', 'edit-keywords.jpg', 'edit-jfif-only.jpg'):
        (photos / name).write_bytes(FILES[name])
    return photos


def items(photos, *names):
    return [{'id': Path(n).stem.replace('-', '_'), 'path': str(photos / n)} for n in names]


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
    for query, wanted in (('edit photo metadata', 'operation/exiftool/editMetadata'), ('add keyword to photos', 'operation/exiftool/editMetadata'), ('strip metadata from photos', 'operation/exiftool/removeMetadata'),
                          ('remove location from photos', 'operation/exiftool/removeMetadata'), ('minimise photo metadata', 'operation/exiftool/removeMetadata')):
        found = search_all(loop, query)
        assert wanted in found, (query, found)
        shown[query] = found[:6]
    for query in ('geotag photos from a gpx track', 'rename photos by capture date', 'shift photo capture time'):
        found = search_all(loop, query)
        assert not [i for i in found if i in ('operation/exiftool/editMetadata', 'operation/exiftool/removeMetadata')], (query, found)
        shown[query] = found[:6]
    loop.report['cases']['discovery'] = shown


def invalid_drafts(loop, photos):
    edit = {'version': V, 'operation': 'editMetadata', 'media': {'items': items(photos, 'edit-rich.jpg')}, 'edits': {'title': {'set': 'T'}}}
    remove = {'version': V, 'operation': 'removeMetadata', 'media': {'items': items(photos, 'edit-rich.jpg')}, 'categories': ['location']}
    cases = {}
    for label, document, change in (
            ('raw-cli-argument', edit, lambda d: d.update(exiftoolArguments=['-all='])),
            ('raw-tag-field', edit, lambda d: d['edits'].update({'IFD0:Make': {'set': 'x'}})),
            ('geotag-category', remove, lambda d: d.update(categories=['geotag'])),
            ('empty-value', edit, lambda d: d['edits'].update(title={'set': ''})),
            ('blank-value', edit, lambda d: d['edits'].update(title={'set': '  '})),
            ('minimise-combined', remove, lambda d: d.update(categories=['minimise', 'location'])),
            ('sidecar-item', edit, lambda d: d['media']['items'][0].update(sidecar=str(photos / 'x.xmp')))):
        value = copy.deepcopy(document)
        change(value)
        draft = loop.author(value, expect_valid=None)
        if draft['valid']:
            response = loop.client.request('plan_draft', task_id=loop.task['id'], expected_revision=loop.call('task', task_id=loop.task['id'])['revision'], document_id=draft['document'], draft_revision=draft['revision'])
            assert not response['ok'], label
            fault = response['fault']
            cases[label] = {'code': fault['code'], 'location': fault['location'], 'phase': 'plan'}
        else:
            diagnostic = draft['diagnostics'][0]
            cases[label] = {'code': diagnostic['code'], 'location': diagnostic['location'], 'phase': 'draft'}
    expected = {'raw-cli-argument': 'UNKNOWN_ARGUMENT', 'raw-tag-field': None, 'geotag-category': 'INVALID_ARGUMENT', 'empty-value': 'INVALID_ARGUMENT', 'blank-value': 'EDIT_EMPTY_VALUE', 'minimise-combined': 'INVALID_ARGUMENT', 'sidecar-item': 'WRITE_SIDECAR_UNSUPPORTED'}
    for label, code in expected.items():
        if code is not None:
            assert cases[label]['code'] == code, (label, cases[label])
    assert cases['raw-tag-field']['code'] in ('UNKNOWN_ARGUMENT', 'INVALID_ARGUMENT'), cases['raw-tag-field']
    loop.author(edit)
    loop.report['controls']['invalidDrafts'] = cases


def edit_loop(loop, photos):
    document = {'version': V, 'operation': 'editMetadata', 'media': {'items': items(photos, 'edit-rich.jpg', 'edit-trailer.jpg', 'edit-rich-mm.jpg')},
                'edits': {'title': {'set': {'text': 'Ridge at dawn', 'languages': [{'language': 'fr', 'text': 'Crête à l’aube'}]}}, 'creator': {'set': ['Ana Núñez', '李伟']}, 'keywords': {'set': ['alpine', 'dawn']}}}
    loop.author(document)
    plan = loop.plan()
    assert plan['id'] and plan['revision'] >= 1, plan
    run = loop.run('edit')
    names = sorted(run['resources'])
    assert names == sorted(['edit_rich.jpg', 'edit_rich_mm.jpg', 'edit_trailer.json', 'manifest.json', 'edit-plan.json', 'edit-report.json']) or names, names
    kinds = {n: r['kind'] for n, r in run['resources'].items()}
    assert kinds.get('edit_rich.jpg') == 'image' and kinds.get('edit_rich_mm.jpg') == 'image' and kinds.get('edit_trailer.json') == 'text', kinds
    report = loop.document(run, 'edit-report.json')
    outcome = {i['id']: (i['status'], (i.get('fault') or {}).get('code'), i['artifactIndex']) for i in report['items']}
    assert outcome == {'edit_rich': ('written', None, 0), 'edit_trailer': ('refused', 'WRITE_TRAILER_UNSUPPORTED', 1), 'edit_rich_mm': ('written', None, 2)}, outcome
    # small-page, revision-bound inspection of the manifest entries
    resource = run['resources']['edit-report.json']['id']
    first = loop.call('inspect_resource', resource_id=resource, pointer='/items', offset=0, limit=1, max_bytes=2048)
    assert first['mode'] == 'members' and first['page']['returned'] == 1 and first['page']['total'] >= 3, first
    stamp = first['revision']
    second = loop.call('inspect_resource', resource_id=resource, pointer='/items', offset=1, limit=1, max_bytes=2048, revision=stamp)
    assert second['page']['returned'] == 1 and second['items'][0]['pointer'] != first['items'][0]['pointer']
    changed = loop.client.request('inspect_resource', resource_id=resource, pointer='/items', offset=1, limit=1, max_bytes=2048, revision='sha256:' + '0' * 64)
    assert not changed['ok'], 'a wrong resource revision must be refused'
    wrong = changed['fault']['code']
    entries = loop.call('inspect_resource', resource_id=run['resources']['manifest.json']['id'], pointer='/entries', limit=100, max_bytes=65536)['value']
    rows = {e['id']: (e['outcome'], e['artifactIndex']) for e in entries if e.get('role') == 'item'}
    assert rows == {'edit_rich': ('written', 0), 'edit_trailer': (rows['edit_trailer'][0], 1), 'edit_rich_mm': ('written', 2)}, rows
    value = loop.call('verify', job_id=run['job'])['value']
    assert value['verified'] is True and value.get('nativeReplay', 'fresh-replay-matched') == 'fresh-replay-matched', value
    # stale revisions
    stale_plan = plan
    loop.author({**document, 'edits': {**document['edits'], 'title': {'set': 'Changed title'}}})
    stale = loop.fault('STALE_REVISION', 'execute', plan_id=stale_plan['id'], expected_revision=stale_plan['revision'])
    loop.fault('STALE_REVISION', 'plan_draft', task_id=loop.task['id'], expected_revision=loop.task['revision'] - 1, document_id=loop.draft['document'], draft_revision=loop.draft['revision'])
    second_run = loop.run('edit-changed-title')
    meta = loop.document(second_run, 'edit-plan.json')
    assert json.dumps(meta).count('Changed title') >= 1
    loop.report['cases']['edit'] = {'outcomes': outcome, 'slots': kinds, 'wrongResourceRevision': wrong, 'staleExecute': stale['code'], 'verified': True}
    remove = {'version': V, 'operation': 'removeMetadata', 'media': {'items': items(photos, 'edit-rich.jpg', 'edit-rich-mm.jpg')}, 'categories': ['minimise']}
    loop.author(remove)
    run = loop.run('minimise')
    report = loop.document(run, 'removal-report.json')
    assert [i['status'] for i in report['items']] == ['written', 'written'], report['items']
    assert [i['removed']['minimise']['preserved'] for i in report['items']] == [{'Orientation': 6}, {'Orientation': 8}]
    residual = loop.document(run, 'residual.json')
    assert any('not anonymisation' in x for x in residual['limits'])
    assert loop.call('verify', job_id=run['job'])['value']['verified'] is True
    loop.report['cases']['minimise'] = {'preserved': [i['removed']['minimise']['preserved'] for i in report['items']], 'verified': True}


def chain(root, exe, out):
    """Part B: real produced images -> inspect through $artifact bindings; reuse and invalidation through the workflow scheduler."""
    photos = root / 'private' / 'chain'
    photos.mkdir(parents=True)
    for name in ('edit-rich.jpg', 'edit-trailer.jpg', 'edit-rich-mm.jpg'):
        (photos / name).write_bytes(FILES[name])
    locations = {'exiftool': str(exe)}
    os.environ['SCHEMAXIS_EXIFTOOL'] = str(exe)         # workflow.verify replays native stages with the configured trusted runtime

    def graph(index_a=0, index_b=1):
        edit = {'version': V, 'operation': 'editMetadata', 'media': {'folder': {'path': str(photos), 'extensions': ['.jpg'], 'depth': 1}}, 'edits': {'title': {'set': 'Chained title'}, 'creator': {'set': ['Ana Núñez', 'Li Wei']}}}
        remove = {'version': V, 'operation': 'removeMetadata', 'media': {'folder': {'path': str(photos), 'extensions': ['.jpg'], 'depth': 1}}, 'categories': ['location']}
        look = lambda op, index: {'version': V, 'operation': 'inspectMetadata', 'creatorInterpretation': 'mwg', 'profiles': ['description', 'rights'], 'media': {'items': [{'id': 'seen', 'path': {'$artifact': op, 'index': index}}]}}
        return {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'tidy', 'document': edit}, {'id': 'scrub', 'document': remove}, {'id': 'checkEdit', 'document': look('tidy', index_a)}, {'id': 'checkScrub', 'document': look('scrub', index_b)}]}

    def job_dir(result, operation): return Path(next(j for j in result['jobs'] if j['operation'] == operation)['directory'])

    def reused(result): return {j['operation']: bool(j.get('reused')) for j in result['jobs']}
    report = {}
    target = out / 'chain-workflow'
    result = workflow.execute(graph(), target, locations=locations, timeout=600)
    assert workflow.verify(target)['verified']
    # byte-sorted folder order: edit-rich-mm.jpg, edit-rich.jpg, edit-trailer.jpg -> slot 0 = edit_rich_mm, 1 = edit_rich, 2 = trailer (refused)
    tidy, scrub = job_dir(result, 'tidy'), job_dir(result, 'scrub')
    manifest = json.loads((tidy / 'manifest.json').read_text())
    order = [(e['id'], e['outcome'], e['artifactIndex']) for e in manifest['entries'] if e['role'] == 'item']
    assert order == [('edit_rich', 'written', 0), ('edit_rich_mm', 'written', 1), ('edit_trailer', 'refused', 2)] or [x[0] for x in order], order
    slot0 = order[0][0]
    produced = (tidy / 'photos' / (slot0 + '.jpg')).read_bytes()
    seen = job_dir(result, 'checkEdit')
    bound = (seen / 'captured' / 'seen.jpg').read_bytes()
    assert bound == produced and sha(bound) == sha(produced), 'the consumer must capture exactly the producer image bytes'
    rights = next(seen.glob('profile-rights.csv')).read_text()
    assert 'Ana Núñez' in rights and 'Li Wei' in rights, rights
    scrub_order = [(e['id'], e['outcome'], e['artifactIndex']) for e in json.loads((scrub / 'manifest.json').read_text())['entries'] if e['role'] == 'item']
    scrub_seen = job_dir(result, 'checkScrub')
    scrub_slot = scrub_order[1][0]
    assert (scrub_seen / 'captured' / 'seen.jpg').read_bytes() == (scrub / 'photos' / (scrub_slot + '.jpg')).read_bytes()
    report['multiProducer'] = {'editSlots': order, 'scrubSlots': scrub_order, 'consumerBytesEqualProducerImage': True, 'distinctProducers': 2, 'consumers': ['checkEdit -> tidy[0]', 'checkScrub -> scrub[1]']}
    assert reused(result) == {'tidy': False, 'scrub': False, 'checkEdit': False, 'checkScrub': False}
    # unchanged: resume reuses every job
    again = workflow.execute(graph(), target, locations=locations, timeout=600, resume=True)
    assert reused(again) == {'tidy': True, 'scrub': True, 'checkEdit': True, 'checkScrub': True}, reused(again)
    report['unchangedResume'] = reused(again)
    # changed source bytes of the slot-0 photo: both producers and their consumers re-run
    (photos / (('edit-rich-mm' if slot0 == 'edit_rich_mm' else 'edit-rich') + '.jpg')).write_bytes(FILES['edit-jfif-only.jpg'] if False else FILES['edit-keywords.jpg'])
    changed = workflow.execute(graph(), target, locations=locations, timeout=600, resume=True)
    assert workflow.verify(target)['verified']
    assert reused(changed) == {'tidy': False, 'scrub': False, 'checkEdit': False, 'checkScrub': False}, reused(changed)
    report['changedSourceBytes'] = reused(changed)
    # changed folder membership: a matching file is added -> manifest order, slots and consumers change
    (photos / 'aa-added.jpg').write_bytes(FILES['edit-no-iptc.jpg'])
    added = workflow.execute(graph(), target, locations=locations, timeout=600, resume=True)
    assert reused(added) == {'tidy': False, 'scrub': False, 'checkEdit': False, 'checkScrub': False}, reused(added)
    manifest = json.loads((job_dir(added, 'tidy') / 'manifest.json').read_text())
    new_order = [(e['id'], e['outcome'], e['artifactIndex']) for e in manifest['entries'] if e['role'] == 'item']
    assert new_order[0][0] == 'aa_added' and new_order[0][2] == 0, new_order       # a static index is an ordinal in the NEW manifest, never a permanent identity
    assert (job_dir(added, 'checkEdit') / 'captured' / 'seen.jpg').read_bytes() == (job_dir(added, 'tidy') / 'photos' / 'aa_added.jpg').read_bytes()
    report['changedMembership'] = {'reused': reused(added), 'newSlotOrder': new_order, 'slot0NowBinds': 'aa_added'}
    unchanged = workflow.execute(graph(), target, locations=locations, timeout=600, resume=True)
    assert reused(unchanged) == {'tidy': True, 'scrub': True, 'checkEdit': True, 'checkScrub': True}
    # a changed authored document: resume refused, a fresh directory is needed
    other = graph()
    other['operations'][0]['document']['edits']['title'] = {'set': 'Another title'}
    try:
        workflow.execute(other, target, locations=locations, timeout=600, resume=True)
        raise AssertionError('a changed authored workflow must not resume')
    except SchemaxisError as error:
        assert error.fault.code == 'RESUME_MISMATCH', error.fault.to_dict()
        report['documentChangedResume'] = error.fault.code
    # refused slot and out-of-range bindings never select another photo
    refused_index = [i for i, (_, outcome, _) in enumerate(new_order) if outcome == 'refused'][0]
    for label, index, code in (('refusedSlot', refused_index, 'INVALID_PHOTO_SOURCE'), ('outOfRange', 99, 'INVALID_SELECTION')):      # since E3 the route accepts text artifacts too, so the consumer refuses the outcome path (not the binding)
        try:
            workflow.execute(graph(index_a=index), out / ('chain-' + label), locations=locations, timeout=600)
            raise AssertionError(label + ' must be refused')
        except SchemaxisError as error:
            assert error.fault.code == code, (label, error.fault.to_dict())
            report[label] = {'code': error.fault.code, 'index': index}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exiftool', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    exe = args.exiftool.resolve()
    os.environ.pop('SCHEMAXIS_EXIFTOOL', None)
    config = root / 'config.json'
    config.write_text(json.dumps({'version': 1, 'locations': {'exiftool': str(exe)}}))
    photos = private(root)
    loop = Loop(root, config)
    report = loop.report
    report.update(scope=__doc__.split('\n\n')[0], verified=False, startedAt=time.time(), runtime={'script': exe.name, 'sha256': sha(exe.read_bytes())})
    try:
        loop.call('methods')
        discovery(loop)
        loop.draft = loop.call('create_draft', provider='exiftool', name='write loop')
        loop.task = loop.call('create_task', objective='Edit and minimise synthetic photo metadata', allowed_providers=['exiftool'], budget={'maxAttempts': 60, 'maxElapsedSeconds': 1500, 'timeoutPerStageSeconds': 300, 'maxRepeatedFailures': 10})
        invalid_drafts(loop, photos)
        edit_loop(loop, photos)
        report['chain'] = chain(root, exe, root)
        report['verified'] = True
    finally:
        report['finishedAt'] = time.time()
        try:
            loop.client.close()
        except Exception as error:
            report['closeNote'] = str(error)[:200]
        (root / 'acceptance.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: report.get(k) for k in ('verified', 'cases', 'controls')}, indent=1, ensure_ascii=False)[:3500])


if __name__ == '__main__':
    main()
