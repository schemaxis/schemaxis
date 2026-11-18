# Copyright (C) 2026 David L. F. Gaden.
"""Serial ParaView proof that ordinary graph edits keep an unchanged resident reader.

Reuses the test-only counting worker of the durable identity qualification: each
proxy's StartEvent is counted by global ID and reported through the existing
status command. One actual file reader feeds derived filters while a sibling is
added, reordered, removed, re-added and reconfigured. The Live Data class drives
the actual data-load transport the same way, adding an unrelated definition edit
and a changed peer reader observed by a consumer of the unchanged reader. No
product command is added.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_paraview_durable_identity import CountingGraph, archive
from test_paraview_live_identity import TETRA, CountingProcess


def document(path, peer, *extra, geometry=('skin',)):
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'mesh', 'filter': 'readPLY', 'options': {'files': [str(path)]}},
        {'id': 'peer', 'filter': 'readPLY', 'options': {'files': [str(peer)]}},
        {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}},
        *extra], 'scenes': [{'id': 'view', 'geometry': list(geometry)}]}


def sibling(factor):
    return {'id': 'extra', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': factor}}


def exercise(directory, executable):
    """Run the bounded sequence; return inspectable evidence without assertions."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path, peer = directory / 'first.ply', directory / 'peer.ply'
    path.write_text(TETRA.format(0, 1))
    peer.write_text(TETRA.format(10, 11))
    states = [
        ('initial', document(path, peer)),
        ('add sibling', document(path, peer, sibling(0.25), geometry=('skin', 'extra'))),
        ('reorder roots', document(path, peer, sibling(0.25), geometry=('extra', 'skin'))),
        ('remove sibling', document(path, peer, sibling(0.25))),
        ('re-add sibling', document(path, peer, sibling(0.25), geometry=('skin', 'extra'))),
        ('change sibling option', document(path, peer, sibling(0.75), geometry=('skin', 'extra'))),
    ]
    evidence = {'steps': []}
    with patch('schemaxis.live_transport.runtime_archive', archive):
        client = CountingGraph(executable, directory / 'native', timeout=120)
        process = client.process
        try:
            for label, value in states:
                applied = client.request('apply', document=value)
                evidence['steps'].append({'label': label, 'applied': applied,
                                          'geometry': client.request('geometry'), 'native': client.request('status')})
        finally:
            client.close()
    evidence['exited'] = process.poll() is not None
    evidence['returncode'] = process.poll()
    return evidence


def points(step, node):
    return [v for o in step['geometry']['objects'] if o['node'] == node for f in o['faces'] for v in f['vertices']]


def bounds(vertices):
    return [f(v[i] for v in vertices) for i in range(3) for f in (min, max)]


def assert_evidence(test, evidence):
    steps = {step['label']: step for step in evidence['steps']}
    first = steps['initial']['native']
    proxies = first['harness']['proxies']
    for step in evidence['steps']:
        native = step['native']
        test.assertEqual(first['pid'], native['pid'])
        for node in ('mesh', 'skin'):
            test.assertEqual(proxies[node]['globalId'], native['harness']['proxies'][node]['globalId'])
            test.assertEqual(1, native['harness']['proxies'][node]['executions'])
        test.assertNotIn('peer', native['harness']['proxies'])
        test.assertNotIn('peer', native['harness']['registered'])
        test.assertEqual(sorted(native['harness']['proxies']), native['harness']['registered'])
        test.assertEqual(points(steps['initial'], 'skin'), points(step, 'skin'))
        test.assertEqual([0.0, 1.0, 0.0, 2.0, 0.0, 3.0], step['geometry']['observations']['mesh']['bounds'])
    added, readded = steps['add sibling']['native']['harness']['proxies'], steps['re-add sibling']['native']['harness']['proxies']
    test.assertEqual(1, added['extra']['executions'])
    test.assertEqual(added['extra'], steps['reorder roots']['native']['harness']['proxies']['extra'])
    test.assertNotIn('extra', steps['remove sibling']['native']['harness']['proxies'])
    test.assertNotEqual(added['extra']['globalId'], readded['extra']['globalId'])
    test.assertEqual(1, readded['extra']['executions'])
    changed = steps['change sibling option']['native']['harness']['proxies']['extra']
    test.assertEqual(readded['extra']['globalId'], changed['globalId'])
    test.assertEqual(2, changed['executions'])
    test.assertEqual(['skin', 'extra'], [o['node'] for o in steps['add sibling']['geometry']['objects']])
    test.assertEqual(['extra', 'skin'], [o['node'] for o in steps['reorder roots']['geometry']['objects']])
    test.assertEqual(points(steps['add sibling'], 'extra'), points(steps['re-add sibling'], 'extra'))
    test.assertEqual(points(steps['add sibling'], 'extra'), points(steps['reorder roots'], 'extra'))
    test.assertEqual(len(points(steps['add sibling'], 'extra')), len(points(steps['change sibling option'], 'extra')))
    narrow, wide = bounds(points(steps['add sibling'], 'extra')), bounds(points(steps['change sibling option'], 'extra'))
    test.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])
    for label, created in (('add sibling', ['extra']), ('reorder roots', []), ('remove sibling', []),
                           ('re-add sibling', ['extra']), ('change sibling option', [])):
        report = steps[label]['applied']['transition']
        test.assertEqual(created, report['created'])
        test.assertEqual({}, report['replaced'])
        test.assertIn('mesh', report['unaffected'])
    test.assertEqual(['extra'], steps['remove sibling']['applied']['transition']['retired'])
    test.assertEqual(['extra'], steps['change sibling option']['applied']['updated'])
    test.assertTrue(evidence['exited'])


def data_document(path, peer, third, *extra, unrelated=1):
    return {'version': 'schemaxis/1', 'definitions': {'unrelated': unrelated}, 'nodes': [
        {'id': 'mesh', 'filter': 'readPLY', 'options': {'files': [str(path)]}},
        {'id': 'peer', 'filter': 'readPLY', 'options': {'files': [str(peer)]}},
        {'id': 'third', 'filter': 'readPLY', 'options': {'files': [str(third)]}},
        {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}},
        {'id': 'probe', 'filter': 'shrink', 'inputs': {'input': 'mesh'},
         'options': {'factor': {'$expr': 'extents(peer).deltaX * 0.5'}}},
        *extra]}


def exercise_data(directory, executable):
    """Drive actual data-load requests through one native Live Data process; return evidence."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path, peer, changed, third = (directory / name for name in ('first.ply', 'peer.ply', 'changed.ply', 'third.ply'))
    path.write_text(TETRA.format(0, 1))
    peer.write_text(TETRA.format(10, 11))
    changed.write_text(TETRA.format(20, 21.6))
    third.write_text(TETRA.format(30, 31))
    base = ['skin', 'probe']
    states = [
        ('initial', data_document(path, peer, third), base),
        ('add sibling', data_document(path, peer, third, sibling(0.25)), [*base, 'extra']),
        ('reorder roots', data_document(path, peer, third, sibling(0.25)), ['extra', 'probe', 'skin']),
        ('remove sibling', data_document(path, peer, third), base),
        ('re-add sibling', data_document(path, peer, third, sibling(0.25)), [*base, 'extra']),
        ('change sibling option', data_document(path, peer, third, sibling(0.75)), [*base, 'extra']),
        ('unrelated definition', data_document(path, peer, third, sibling(0.75), unrelated=2), [*base, 'extra']),
        ('changed peer file', data_document(path, changed, third, sibling(0.75), unrelated=2), [*base, 'extra']),
    ]
    evidence = {'steps': [], 'requests': []}
    CountingProcess.started = []
    with patch('schemaxis.live_transport.runtime_archive', archive):
        client = CountingProcess('paraview', executable, directory / 'native', 120)
        process = client.process
        try:
            for label, value, roots in states:
                reply = client.request('data-load', document=value, roots=roots, state={'timeIndex': 0, 'indices': {}})
                evidence['requests'].append('data-load')
                inspected = {}
                for node in reply['nodes']:
                    result = client.request('data-inspect', node=node, port=0, geometry=True)
                    evidence['requests'].append('data-inspect')
                    inspected[node] = {'observation': {k: result['observation'][k]
                                                       for k in ('bounds', 'points', 'cells', 'dataType')},
                                       'geometry': result['geometry']['objects'] if result.get('geometry') else None}
                evidence['steps'].append({'label': label, 'roots': roots, 'reply': reply, 'inspected': inspected,
                                          'native': client.request('status')})
                evidence['requests'].append('status')
        finally:
            client.close()
    evidence['started'] = len(CountingProcess.started)
    evidence['exited'] = process.poll() is not None
    evidence['returncode'] = process.poll()
    return evidence


def assert_data(test, evidence):
    steps = {step['label']: step for step in evidence['steps']}
    first = steps['initial']['native']
    proxies = first['harness']['proxies']
    test.assertEqual(1, evidence['started'])
    for step in evidence['steps']:
        native = step['native']
        test.assertEqual(first['pid'], native['pid'])
        test.assertFalse(native['uncertain'])
        for node in ('mesh', 'skin'):
            test.assertEqual(proxies[node]['globalId'], native['harness']['proxies'][node]['globalId'])
            test.assertEqual(1, native['harness']['proxies'][node]['executions'])
        test.assertEqual(proxies['probe']['globalId'], native['harness']['proxies']['probe']['globalId'])
        test.assertNotIn('third', native['harness']['proxies'])
        test.assertEqual(sorted([*native['harness']['proxies'], 'occupied']), native['harness']['registered'])
        test.assertEqual(steps['initial']['inspected']['skin'], step['inspected']['skin'])
        test.assertEqual([0.0, 1.0, 0.0, 2.0, 0.0, 3.0], step['inspected']['mesh']['observation']['bounds'])
        test.assertTrue(step['reply']['reused'] or step['label'] == 'initial')
    added = steps['add sibling']['native']['harness']['proxies']['extra']
    readded = steps['re-add sibling']['native']['harness']['proxies']['extra']
    test.assertEqual(1, added['executions'])
    test.assertEqual(added, steps['reorder roots']['native']['harness']['proxies']['extra'])
    test.assertNotIn('extra', steps['remove sibling']['native']['harness']['proxies'])
    test.assertNotEqual(added['globalId'], readded['globalId'])
    test.assertEqual(1, readded['executions'])
    changed = steps['change sibling option']['native']['harness']['proxies']['extra']
    test.assertEqual((readded['globalId'], 2), (changed['globalId'], changed['executions']))
    test.assertEqual(steps['add sibling']['inspected']['extra'], steps['re-add sibling']['inspected']['extra'])
    test.assertNotEqual(steps['add sibling']['inspected']['extra'], steps['change sibling option']['inspected']['extra'])
    for label, created in (('add sibling', ['extra']), ('reorder roots', []), ('remove sibling', []),
                           ('re-add sibling', ['extra']), ('change sibling option', []), ('unrelated definition', []),
                           ('changed peer file', ['peer'])):
        test.assertEqual(created, steps[label]['reply']['created'])
    test.assertEqual([], steps['unrelated definition']['reply']['updated'])
    test.assertEqual(steps['change sibling option']['native']['harness']['proxies'],
                     steps['unrelated definition']['native']['harness']['proxies'])
    before, after = steps['unrelated definition'], steps['changed peer file']
    old_peer, new_peer = before['native']['harness']['proxies']['peer'], after['native']['harness']['proxies']['peer']
    test.assertNotEqual(old_peer['globalId'], new_peer['globalId'])
    test.assertEqual(1, new_peer['executions'])
    probe = after['native']['harness']['proxies']['probe']
    test.assertEqual(before['native']['harness']['proxies']['probe']['executions'] + 1, probe['executions'])
    test.assertEqual(sorted(['peer', 'probe']), sorted(after['reply']['updated']))
    for actual, wanted in zip(after['inspected']['peer']['observation']['bounds'], [20, 21.6, 0, 2, 0, 3]):
        test.assertAlmostEqual(wanted, actual, places=5)
    narrow = before['inspected']['probe']['observation']['bounds']
    wide = after['inspected']['probe']['observation']['bounds']
    test.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])
    test.assertEqual(before['inspected']['probe']['observation']['points'], after['inspected']['probe']['observation']['points'])
    test.assertTrue(evidence['exited'])


class NativeResidentTransition(unittest.TestCase):
    def test_reader_survives_ordinary_sibling_edits_serially(self):
        from schemaxis.adaptors.paraview.mvp.runners import find_paraview
        executable = find_paraview()
        if not executable: self.skipTest('ParaView is not configured')
        with tempfile.TemporaryDirectory() as temporary:
            assert_evidence(self, exercise(Path(temporary), executable[0].executable))


class NativeResidentDataTransition(unittest.TestCase):
    def test_data_load_keeps_unchanged_reader_beside_changed_peer_serially(self):
        from schemaxis.adaptors.paraview.mvp.runners import find_paraview
        executable = find_paraview()
        if not executable: self.skipTest('ParaView is not configured')
        with tempfile.TemporaryDirectory() as temporary:
            assert_data(self, exercise_data(Path(temporary), executable[0]))


if __name__ == '__main__': unittest.main()
