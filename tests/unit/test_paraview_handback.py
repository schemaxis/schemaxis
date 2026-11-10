import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview import handback
from schemaxis.adaptors.paraview.job import plan, identities, schedule

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'examples' / 'schemaxis' / 'paraview-state-bundle.json'


def document(**scene):
    value = json.loads(EXAMPLE.read_text())
    value['scenes'][0].update(scene)
    return value


def code(callable_, *args):
    try:
        callable_(*args)
    except SchemaxisError as error:
        return error.fault.code, error.fault.message
    raise AssertionError('expected a structured fault')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Planning(unittest.TestCase):
    def test_generated_example_plans_bundle_identity_without_native_imports(self):
        script = ('import json, sys\nfrom schemaxis.adaptors.paraview.job import plan\n'
                  f'master, scenes, resolved = plan(json.load(open({str(EXAMPLE)!r})))\n'
                  'assert scenes[0]["stateBundle"] is True and resolved["expectedPublications"] == 2\n'
                  'assert not [m for m in sys.modules if m == "paraview" or m.startswith(("paraview.", "vtkmodules"))]\n')
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        subprocess.run([sys.executable, '-c', script], check=True, env=environment)
        master, scenes, _ = plan(document())
        kinds = [i['kind'] for scene, visit in schedule(master, scenes) for i in identities(scene, visit)]
        self.assertEqual(kinds, ['image', 'state-bundle'])

    def test_requests_without_option_keep_previous_plan_and_identities(self):
        value = document()
        del value['scenes'][0]['stateBundle']
        master, scenes, resolved = plan(value)
        self.assertNotIn('stateBundle', scenes[0])
        self.assertEqual(resolved['expectedPublications'], 1)
        kinds = [i['kind'] for scene, visit in schedule(master, scenes) for i in identities(scene, visit)]
        self.assertEqual(kinds, ['image'])

    def test_malformed_option_is_rejected(self):
        for value in ('yes', 1, {'format': 'pvsm'}, '/tmp/other.pvsm'):
            self.assertEqual(code(plan, document(stateBundle=value))[0], 'INVALID_PUBLICATION')

    def test_unsupported_modes_are_refused_during_planning(self):
        image = {'id': 'view', 'cameras': [{}]}
        cases = {
            'times': {**document(), 'times': [0, 1]},
            'appearances': document(appearances=[{}, {'half': {'opacity': 0.5}}]),
            'no image': document(images=[]),
            'two cameras': document(images=[{'id': 'view', 'cameras': [{}, {'direction': [1, 0, 0]}]}]),
            'two writers': document(images=[image, {**image, 'id': 'other'}]),
            'gltf': document(gltf=True),
        }
        two = document()
        two['scenes'].append({'id': 'other', 'visible': {'ball': {}}, 'images': [image]})
        cases['scenes'] = two
        axis = document()
        axis['axes'] = [{'name': 'r', 'values': [0.5, 1]}]
        axis['nodes'][0]['options']['radius'] = {'$axis': 'r'}
        cases['axis'] = axis
        for label, value in cases.items():
            with self.subTest(label):
                self.assertEqual(code(plan, value)[0], 'UNSUPPORTED_STATE_BUNDLE')

    def test_reader_policy_is_bounded(self):
        foam = document()
        foam['nodes'] = [{'id': 'case', 'filter': 'foam', 'options': {'file': '/data/case.foam'}}]
        foam['scenes'][0]['visible'] = {'case': {}}
        self.assertEqual(code(plan, foam)[0], 'UNSUPPORTED_STATE_BUNDLE')
        multiblock = copy.deepcopy(foam)
        multiblock['nodes'] = [{'id': 'case', 'filter': 'readMultiBlock', 'options': {'files': ['/data/a.vtm']}}]
        self.assertEqual(code(plan, multiblock)[0], 'UNSUPPORTED_STATE_BUNDLE')
        surface = copy.deepcopy(foam)
        surface['nodes'] = [{'id': 'plate', 'filter': 'readSurface', 'options': {'files': ['/data/plate.vtp']}},
                            {'id': 'half', 'filter': 'clip', 'inputs': {'input': 'plate'}}]
        surface['scenes'][0]['visible'] = {'half': {}}
        self.assertTrue(plan(surface)[1][0]['stateBundle'])

    def test_captured_single_file_example_plans(self):
        sys.path.insert(0, str(ROOT / 'examples' / 'schemaxis'))
        try:
            import check_state_bundle as example
        finally:
            sys.path.pop(0)
        from schemaxis.captured_inputs import adopt
        from schemaxis.workflow import provisional_plan
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'plate.vtp'
            source.write_text(example.surface())
            adopted = adopt(source, Path(temporary) / 'snapshot')
            operation = example.workflow(adopted['reference'])['operations'][0]['document']
            result = provisional_plan(operation)
            self.assertTrue(result['scenes'][0]['stateBundle'])
            self.assertEqual(result['capturedInputs'][0]['policy']['reader'], 'readSurface')

    def test_mpi_refuses_bundles(self):
        from schemaxis.adaptors.paraview.execution import validate_mpi
        self.assertEqual(code(validate_mpi, document())[0], 'UNSUPPORTED_MPI_PUBLICATION')

    def test_no_authored_state_loading(self):
        from schemaxis.adaptors.paraview.filters import catalogue
        from schemaxis.adaptors.paraview.schema import document_schema
        self.assertFalse([k for k, d in catalogue().items() if 'loadstate' in (k + str(d.get('native'))).lower()])
        self.assertIn('"stateBundle": {"type": "boolean"', json.dumps(document_schema()))
        calls = [str(p.relative_to(ROOT)) for p in (ROOT / 'src').rglob('*.py')
                 if re.search(r'\bLoadState\(', p.read_text(errors='replace'))]
        self.assertEqual(calls, ['src/schemaxis/adaptors/paraview/handback_native.py'])


def _capture(root, node, source):
    from schemaxis import workflow_resources as resources
    resource, relative = handback.member_layout(node, Path(source).name)
    captured = resources.capture(source, root / resource, kind='file', max_files=1,
                                 max_bytes=handback.LIMITS['fileBytes'])
    record, = captured['files']
    return {'node': node, 'path': relative, 'resource': resource, 'sha256': record['sha256'],
            'bytes': record['size'], 'origin': str(Path(source).resolve()), 'property': 'FileName',
            'resourceDigest': captured['digest'], 'resourceSha256': sha(root / resource / 'resource.json'),
            'proxyId': '7'}


OBSERVATION = {'dataType': 'vtkPolyData', 'points': 4, 'cells': 1, 'bounds': [0, 1, 0, 1, 0, 0],
               'fields': {'POINTS': {'pressure': {'components': 1, 'range': [1.0, 2.0]}}, 'CELLS': {}}}
CAMERA = {'position': [0, 0, 5], 'focalPoint': [0, 0, 0], 'up': [0, 1, 0], 'parallel': True, 'scale': 1.0,
          'viewAngle': 30.0}
PRESENTATION = {'points': [1.0, 0.2, 0.3, 0.8, 2.0, 0.7, 0.0, 0.1], 'logScale': False, 'legendVisible': True,
                'legendTitle': 'pressure (units unknown)'}
CLIP = [{'option': 'origin', 'path': ['ClipType', 'Origin'], 'raw': False, 'value': [0.1, 0.0, 0.0]},
        {'option': 'normal', 'path': ['ClipType', 'Normal'], 'raw': False, 'value': [1.0, 0.0, 0.0]},
        {'option': 'invert', 'path': ['Invert'], 'raw': False, 'value': 0}]


def bundle(directory, origin=None):
    """Write a well-formed bundle as the native save would, capturing through workflow_resources."""
    directory = Path(directory)
    source = directory / 'source' / 'plate.vtp'
    source.parent.mkdir(parents=True)
    source.write_text('<VTKFile type="PolyData"/>')
    root = directory / '000000-editable-state-bundle'
    (root / 'data').mkdir(parents=True)
    member = _capture(root, 'plate', source)
    if origin is not None:
        member['origin'] = origin
    data = root / member['path']
    (root / 'state.pvsm').write_text(
        '<ParaView><ServerManagerState><Proxy group="sources" type="XMLPolyDataReader" id="7">'
        f'<Property name="FileName"><Element index="0" value="{data}"/></Property></Proxy>'
        '<Proxy group="filters" type="Clip" id="9"/></ServerManagerState></ParaView>')
    manifest = {'version': handback.VERSION, 'state': handback.STATE, 'stateSha256': sha(root / 'state.pvsm'),
                'savedBundle': str(root.resolve()), 'scene': 'editable', 'time': 0, 'viewTime': 0.0,
                'members': [member],
                'pipeline': {'plate': {'proxyId': '7', 'xmlName': 'XMLPolyDataReader', 'inputs': [],
                                       'filter': 'readSurface', 'properties': []},
                             'half': {'proxyId': '9', 'xmlName': 'Clip', 'inputs': ['Input=plate:0'],
                                      'filter': 'clip', 'properties': copy.deepcopy(CLIP)}},
                'observations': {'plate': OBSERVATION, 'half': OBSERVATION},
                'appearance': {'half': {'colour': ['POINTS', 'pressure'], 'opacity': 1.0,
                                        'representation': 'Surface With Edges'}},
                'presentation': {'half': dict(PRESENTATION)},
                'camera': CAMERA, 'viewSize': [64, 48],
                'runtimeIdentity': {'application': 'paraview', 'version': '5.13.3'}, 'processId': 100,
                'pathStrategy': '', 'openInParaView': handback.GUI_STEPS, 'units': 'unknown', 'frame': 'unknown',
                'losses': handback.LOSSES, 'scope': handback.SCOPE, 'proofScope': handback.PROOF_SCOPE}
    (root / 'bundle.json').write_text(json.dumps(manifest))
    return root, manifest


def proof(root, manifest, relocated):
    data = relocated / 'data'
    return {'version': handback.RELOAD_VERSION, 'status': 'succeeded', 'verified': True,
            'relocatedBundle': str(relocated), 'processId': 200,
            'withheld': {'path': str(root), 'absentDuringReload': True},
            'manifestSha256': sha(root / 'bundle.json'), 'stateSha256': manifest['stateSha256'],
            'runtimeIdentity': {'application': 'paraview', 'version': '5.13.3'},
            'loadOptions': {'dataDirectory': str(data), 'restrictToDataDirectory': True},
            'viewSize': [64, 48], 'viewTime': 0.0,
            'pipeline': {'plate': {'xmlName': 'XMLPolyDataReader', 'inputs': [], 'properties': [],
                                   'fileProperties': {'FileName': [str(data / 'plate' / 'data' / 'plate.vtp')]}},
                         'half': {'xmlName': 'Clip', 'inputs': ['Input=plate:0'], 'properties': copy.deepcopy(CLIP),
                                  'fileProperties': {}}},
            'observations': copy.deepcopy(manifest['observations']),
            'appearance': copy.deepcopy(manifest['appearance']),
            'presentation': copy.deepcopy(manifest['presentation']), 'camera': copy.deepcopy(manifest['camera'])}


class Bundle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root, self.manifest = bundle(self.temporary.name)
        self.relocated = Path(self.temporary.name) / 'moved' / 'bundle'
        self.digest = sha(self.root / 'bundle.json')

    def rewrite(self, manifest):
        (self.root / 'bundle.json').write_text(json.dumps(manifest))

    def test_well_formed_bundle_and_reload_verify(self):
        self.assertEqual(handback.check_bundle(self.root)['members'][0]['node'], 'plate')
        handback.verify_reload(proof(self.root, self.manifest, self.relocated), self.manifest, self.digest)
        from schemaxis import workflow_resources as resources
        self.assertEqual(resources.verify(self.root / 'data' / 'plate', max_files=1)['digest'],
                         self.manifest['members'][0]['resourceDigest'])

    def test_tampered_missing_and_extra_members_fail(self):
        labels = ('tampered dataset', 'tampered state', 'missing dataset', 'missing state', 'extra file',
                  'symbolic link', 'tampered resource manifest', 'missing resource manifest', 'extra directory',
                  'file inside capture')
        for label in labels:
            with self.subTest(label):
                root, _ = bundle(Path(self.temporary.name) / label.replace(' ', '-'))
                data, state = root / 'data' / 'plate' / 'data' / 'plate.vtp', root / 'state.pvsm'
                record = root / 'data' / 'plate' / 'resource.json'
                {'tampered dataset': lambda: data.write_text('<VTKFile type="PolyData" changed="1"/>'),
                 'tampered state': lambda: state.write_text(state.read_text() + ' '),
                 'missing dataset': data.unlink,
                 'missing state': state.unlink,
                 'extra file': lambda: (root / 'data' / 'extra.vtp').write_text('x'),
                 'symbolic link': lambda: (root / 'link').symlink_to(data),
                 'tampered resource manifest': lambda: record.write_text(record.read_text() + ' '),
                 'missing resource manifest': record.unlink,
                 'extra directory': lambda: (root / 'data' / 'other').mkdir(),
                 'file inside capture': lambda: (root / 'data' / 'plate' / 'note.txt').write_text('x')}[label]()
                self.assertEqual(code(handback.check_bundle, root)[0], 'VERIFICATION_FAILED')

    def test_publication_companions_only_at_bundle_top_level(self):
        top = self.root / 'state.pvsm.metadata.json'
        top.write_text('{}')
        handback.check_bundle(self.root, self.digest, {top.resolve()})
        inside = self.root / 'data' / 'plate' / 'data' / 'plate.vtp.metadata.json'
        inside.write_text('{}')
        self.assertEqual(code(handback.check_bundle, self.root, self.digest, {top.resolve(), inside.resolve()})[0],
                         'VERIFICATION_FAILED')

    def test_manifest_digest_and_typed_member_rules(self):
        self.assertEqual(code(handback.check_bundle, self.root, '0' * 64)[0], 'VERIFICATION_FAILED')
        good = self.manifest['members'][0]
        for change in ({'path': 'data/../outside.vtp'}, {'path': '/abs/plate.vtp'}, {'path': 'plate.vtp'},
                       {'path': 'data/plate/plate.vtp'}, {'resource': 'data/other'},
                       {'bytes': handback.LIMITS['fileBytes'] + 1}, {'bytes': -1}, {'bytes': True}, {'bytes': '3'},
                       {'sha256': 'x'}, {'node': 7}, {'node': '../x'}, {'origin': 'relative.vtp'},
                       {'property': 'Other'}, {'proxyId': None}):
            with self.subTest(change):
                manifest = copy.deepcopy(self.manifest)
                manifest['members'][0].update(change)
                self.rewrite(manifest)
                self.assertEqual(code(handback.check_bundle, self.root)[0], 'VERIFICATION_FAILED')
        for label, value in {'missing key': {k: v for k, v in good.items() if k != 'sha256'},
                             'not an object': ['plate'], 'duplicate': None}.items():
            with self.subTest(label):
                manifest = copy.deepcopy(self.manifest)
                manifest['members'] = [good, good] if value is None else [value]
                self.rewrite(manifest)
                self.assertEqual(code(handback.check_bundle, self.root)[0], 'VERIFICATION_FAILED')

    def test_malformed_bytes_json_and_xml_are_structured_failures(self):
        manifest_cases = {'array manifest': b'[]', 'invalid json': b'{', 'not utf-8': b'\xff\xfe',
                          'nonfinite': b'{"version": NaN}', 'deep': b'[' * 100000 + b']' * 100000,
                          'string': b'"bundle"', 'pid bool': json.dumps({**self.manifest, 'processId': True}).encode(),
                          'size wrong': json.dumps({**self.manifest, 'viewSize': [64]}).encode()}
        for label, payload in manifest_cases.items():
            with self.subTest(label):
                (self.root / 'bundle.json').write_bytes(payload)
                self.assertEqual(code(handback.check_bundle, self.root)[0], 'VERIFICATION_FAILED')
        self.rewrite(self.manifest)
        for label, payload in {'xml': b'<ParaView><unclosed>', 'xml bytes': b'\xff<x/>',
                               'entity': b'<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'}.items():
            with self.subTest(label):
                (self.root / 'state.pvsm').write_bytes(payload)
                manifest = dict(self.manifest, stateSha256=sha(self.root / 'state.pvsm'))
                self.rewrite(manifest)
                self.assertEqual(code(handback.check_bundle, self.root)[0], 'VERIFICATION_FAILED')

    def test_symlinked_manifest_target_is_never_read(self):
        sentinel = Path(self.temporary.name) / 'outside-sentinel.json'
        sentinel.write_text(json.dumps(self.manifest))
        (self.root / 'bundle.json').unlink()
        (self.root / 'bundle.json').symlink_to(sentinel)
        opened = []
        real_open, real_os_open = open, os.open
        def watch(path, *args, **kwargs):
            opened.append(os.path.realpath(path))
            return real_os_open(path, *args, **kwargs)
        def watch_builtin(path, *args, **kwargs):
            opened.append(os.path.realpath(path))
            return real_open(path, *args, **kwargs)
        from unittest import mock
        with mock.patch('os.open', watch), mock.patch('builtins.open', watch_builtin), \
                mock.patch('io.open', watch_builtin):
            self.assertEqual(code(handback.check_bundle, self.root)[0], 'VERIFICATION_FAILED')
        self.assertNotIn(os.path.realpath(sentinel), opened)
        # A symlinked bundle ancestor is refused before any member is opened.
        alias = Path(self.temporary.name) / 'alias'
        alias.symlink_to(self.root.parent)
        with mock.patch('os.open', watch):
            opened.clear()
            self.assertEqual(code(handback.check_bundle, alias / self.root.name)[0], 'VERIFICATION_FAILED')
        self.assertEqual(opened, [])

    def test_fifo_and_oversized_files_are_refused_without_reading(self):
        from unittest import mock
        state = self.root / 'state.pvsm'
        state.unlink()
        os.mkfifo(state)
        self.assertEqual(code(handback.check_bundle, self.root)[0], 'VERIFICATION_FAILED')  # would block if opened
        state.unlink()
        with open(state, 'wb') as stream:
            stream.truncate(handback.LIMITS['stateBytes'] + 1)
        self.rewrite(dict(self.manifest, stateSha256='0' * 64))
        from schemaxis import workflow_resources as resources
        real, opened = resources._open_read, []
        def guarded(path):
            opened.append(Path(path).name)
            if Path(path).name == 'state.pvsm':
                raise AssertionError('oversized state was opened')
            return real(path)
        with mock.patch.object(resources, '_open_read', guarded):
            result = code(handback.check_bundle, self.root)
        self.assertEqual(result[0], 'VERIFICATION_FAILED')
        self.assertIn('size limit', result[1])
        self.assertNotIn('state.pvsm', opened)
        proof_path = self.root.with_name(self.root.name + '.reload.json')
        os.mkfifo(proof_path)
        self.assertEqual(code(handback.read_json, proof_path, 100)[0], 'VERIFICATION_FAILED')

    def test_state_must_not_reference_originals_or_other_paths(self):
        root, _ = bundle(Path(self.temporary.name) / 'origin', origin=str(Path(self.temporary.name)))
        self.assertIn('original input', code(handback.check_bundle, root)[1])
        state = self.root / 'state.pvsm'
        text = state.read_text().replace(self.manifest['members'][0]['path'], 'data/plate/other.vtp')
        state.write_text(text)
        self.rewrite(dict(self.manifest, stateSha256=sha(state)))
        self.assertIn('bundle copy', code(handback.check_bundle, self.root)[1])

    def test_origins_that_end_the_bundle_copy_path_are_not_references(self):
        # The copy is always .../data/<node>/data/<name>; these origins are its suffixes.
        for origin in ('/data/plate.vtp', '/plate.vtp', '/plate/data/plate.vtp', '/source/plate.vtp'):
            with self.subTest(origin):
                root, _ = bundle(Path(self.temporary.name) / origin.replace('/', '_'), origin=origin)
                self.assertEqual(handback.check_bundle(root)['members'][0]['origin'], origin)

    def test_decoded_original_references_are_refused(self):
        from xml.sax.saxutils import quoteattr, escape
        for index, origin in enumerate(('/data/plate.vtp', '/inputs/a&b.vtp', '/inputs/say "hi".vtp',
                                        "/inputs/it's.vtp", '/inputs/a<b.vtp')):
            for label, xml in {'element value': f'<Property name="Note"><Element index="0" value={quoteattr(origin)}/>'
                                                '</Property>',
                               'listed value': f'<Property name="Note"><Element index="0" '
                                               f'value={quoteattr("other.vtp;" + origin)}/></Property>',
                               'beneath origin': f'<Property name="Note"><Element index="0" '
                                                 f'value={quoteattr(origin + "/x")}/></Property>',
                               'text': f'<Note>{escape(origin)}</Note>'}.items():
                with self.subTest(origin=origin, where=label):
                    root, manifest = bundle(Path(self.temporary.name) / f'{label}-{index}', origin=origin)
                    state = root / 'state.pvsm'
                    state.write_text(state.read_text().replace('<Proxy group="filters" type="Clip" id="9"/>',
                                                               f'<Proxy group="filters" type="Clip" id="9">{xml}'
                                                               '</Proxy>'))
                    (root / 'bundle.json').write_text(json.dumps(dict(manifest, stateSha256=sha(state))))
                    self.assertIn('original input', code(handback.check_bundle, root)[1])

    def test_reload_evidence_rejections(self):
        good = proof(self.root, self.manifest, self.relocated)
        data = self.relocated / 'data'
        plate, half = good['pipeline']['plate'], good['pipeline']['half']
        cases = {
            'failed': {'status': 'failed'},
            'unverified': {'verified': False},
            'other bundle': {'manifestSha256': '0' * 64},
            'in place': {'relocatedBundle': str(self.root)},
            'not withheld': {'withheld': {'path': str(self.root), 'absentDuringReload': False}},
            'same process': {'processId': 100},
            'bool process': {'processId': True},
            'negative process': {'processId': -3},
            'string process': {'processId': '200'},
            'missing process': {'processId': None},
            'other runtime': {'runtimeIdentity': {'application': 'paraview', 'version': '6.0.0'}},
            'faulted runtime': {'runtimeIdentity': {'application': 'paraview', 'version': '5.13.3', 'fault': 'x'}},
            'wrong size': {'viewSize': [640, 480]},
            'wrong time': {'viewTime': 1.0},
            'unrestricted': {'loadOptions': {'dataDirectory': str(data), 'restrictToDataDirectory': False}},
            'other data directory': {'loadOptions': {'dataDirectory': str(self.root / 'data'),
                                                     'restrictToDataDirectory': True}},
            'path rebind': {'pipeline': {**good['pipeline'],
                                         'plate': {**plate, 'fileProperties': {'FileName': ['/original/plate.vtp']}}}},
            'replacement reader': {'pipeline': {**good['pipeline'], 'plate': {**plate, 'xmlName': 'STLReader'}}},
            'extra object': {'pipeline': {**good['pipeline'], 'other': {'xmlName': 'Sphere', 'inputs': []}}},
            'unbound file property': {'pipeline': {**good['pipeline'],
                                                   'half': {**half, 'fileProperties': {'X[0].FileName': ['/x']}}}},
            'clip origin': {'pipeline': {**good['pipeline'], 'half': {**half, 'properties': [
                {**CLIP[0], 'value': [0.0, 0.0, 0.0]}, *CLIP[1:]]}}},
            'missing readback': {'pipeline': {**good['pipeline'], 'half': {**half, 'properties': None}}},
            'changed data': {'observations': {**good['observations'],
                                              'plate': {**good['observations']['plate'], 'points': 5}}},
            'changed style': {'appearance': {'half': {**good['appearance']['half'], 'opacity': 0.5}}},
            'changed range': {'presentation': {'half': {**PRESENTATION, 'points': [0.0] + PRESENTATION['points'][1:]}}},
            'hidden legend': {'presentation': {'half': {**PRESENTATION, 'legendVisible': False}}},
            'legend title': {'presentation': {'half': {**PRESENTATION, 'legendTitle': 'pressure'}}},
            'changed camera': {'camera': {**good['camera'], 'position': [0, 0, 6]}},
        }
        for label, change in cases.items():
            with self.subTest(label):
                self.assertEqual(code(handback.verify_reload, {**good, **change}, self.manifest, self.digest)[0],
                                 'VERIFICATION_FAILED')
        for label, value in {'list': [], 'missing pipeline': {k: v for k, v in good.items() if k != 'pipeline'},
                             'missing viewSize': {k: v for k, v in good.items() if k != 'viewSize'},
                             'pipeline entry list': {**good, 'pipeline': {'plate': [], 'half': half}}}.items():
            with self.subTest(label):
                self.assertEqual(code(handback.verify_reload, value, self.manifest, self.digest)[0],
                                 'VERIFICATION_FAILED')

    def test_duplicate_reader_basenames_must_resolve_to_their_own_member(self):
        second = Path(self.temporary.name) / 'second' / 'plate.vtp'
        second.parent.mkdir()
        second.write_text('<VTKFile type="PolyData" second="1"/>')
        member = dict(_capture(self.root, 'other', second), proxyId='11')
        manifest = copy.deepcopy(self.manifest)
        manifest['members'].append(member)
        manifest['pipeline']['other'] = {'proxyId': '11', 'xmlName': 'XMLPolyDataReader', 'inputs': [],
                                         'filter': 'readSurface', 'properties': []}
        manifest['observations']['other'] = OBSERVATION
        state = self.root / 'state.pvsm'
        state.write_text(state.read_text().replace(
            '</ServerManagerState>', '<Proxy group="sources" type="XMLPolyDataReader" id="11"><Property '
            f'name="FileName"><Element index="0" value="{self.root / member["path"]}"/></Property></Proxy>'
            '</ServerManagerState>'))
        manifest['stateSha256'] = sha(state)
        self.rewrite(manifest)
        self.assertEqual(len(handback.check_bundle(self.root)['members']), 2)
        digest = sha(self.root / 'bundle.json')
        good = proof(self.root, manifest, self.relocated)
        data = self.relocated / 'data'
        good['pipeline']['other'] = {'xmlName': 'XMLPolyDataReader', 'inputs': [], 'properties': [],
                                     'fileProperties': {'FileName': [str(data / 'other' / 'data' / 'plate.vtp')]}}
        good['observations']['other'] = OBSERVATION
        handback.verify_reload(good, manifest, digest)
        # ParaView's directory search resolving both readers to one copy must fail clearly.
        crossed = copy.deepcopy(good)
        crossed['pipeline']['other']['fileProperties'] = copy.deepcopy(good['pipeline']['plate']['fileProperties'])
        fault = code(handback.verify_reload, crossed, manifest, digest)
        self.assertEqual(fault[0], 'VERIFICATION_FAILED')
        self.assertIn('exactly the relocated bundle copy', fault[1])

    def test_reload_withholds_original_and_restores_it(self):
        artifact = {'identity': {'kind': 'state-bundle'}, 'file': str(self.root / 'state.pvsm'),
                    'manifestSha256': self.digest}
        seen = []

        class Submission:
            def to_dict(self):
                return {'exitCode': 0}

        def runner(source):
            seen.append((self.root.exists(), re.findall(r"'([^']+)'", source)))
            return Submission()
        handback.reload(self.temporary.name, {'artifacts': [artifact]}, runner)
        (exists, (relocated, original, _, digest)), = seen
        self.assertEqual(digest, self.digest)
        self.assertFalse(exists)
        self.assertEqual(original, str(self.root))
        self.assertTrue(self.root.is_dir() and not Path(relocated).exists())

        with self.assertRaises(Exception):
            handback.reload(Path(self.temporary.name), {'artifacts': [artifact]}, lambda s: 1 / 0)
        self.assertTrue(self.root.is_dir())


def surface_document(origin):
    return {'version': 'schemaxis/1',
            'nodes': [{'id': 'plate', 'filter': 'readSurface', 'options': {'files': [str(origin)]}},
                      {'id': 'half', 'filter': 'clip', 'inputs': {'input': 'plate'},
                       'options': {'origin': [0.1, 0, 0], 'normal': [1, 0, 0]}}],
            'scenes': [{'id': 'editable',
                        'visible': {'half': {'field': ['POINTS', 'pressure'], 'legend': True,
                                             'legendTitle': 'pressure (units unknown)', 'range': [1.0, 2.0],
                                             'representation': 'Surface With Edges'}},
                        'images': [{'id': 'view', 'size': [64, 48], 'cameras': [{}]}], 'stateBundle': True}]}


class Artifact(unittest.TestCase):
    """Host verification of a retained bundle against the plan, run state and image receipt."""

    def setUp(self):
        from schemaxis.adaptors.paraview.publication import style
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root, self.manifest = bundle(self.directory)
        origin = self.manifest['members'][0]['origin']
        self.master, scenes, _ = plan(surface_document(origin))
        self.scene = scenes[0]
        member = self.manifest['members'][0]
        self.state = {'proxyIds': {'plate': '7', 'half': '9'}, 'observations': {'plate': OBSERVATION,
                                                                               'half': OBSERVATION},
                      'visit': {'time': 0.0, 'timeIndex': 0, 'indices': {}},
                      'effective': {'plate': {'files': [origin]}},
                      'inputRebinding': {'plate': {
                          'property': 'FileName', 'origin': origin,
                          'captured': str(self.root.resolve() / member['path']), 'sha256': member['sha256'],
                          'resourceDigest': member['resourceDigest'], 'bytes': member['bytes'],
                          'resourceSha256': member['resourceSha256']}}}
        effective = {'half': style(self.scene['appearances'][0]['half'], 'half')}
        self.image = {'appearance': copy.deepcopy(self.manifest['appearance']), 'camera': CAMERA,
                      'dimensions': [64, 48, 3], 'viewTime': 0.0, 'effectiveAppearance': effective}
        self.artifact = {'file': str(self.root / 'state.pvsm'), 'manifestSha256': sha(self.root / 'bundle.json'),
                         'files': [{'path': 'bundle.json'}],
                         'capturedInputs': [{k: member[k] for k in ('node', 'resource', 'resourceSha256',
                                                                    'resourceDigest', 'path', 'sha256', 'bytes')}]}
        self.proof = self.root.with_name(self.root.name + '.reload.json')
        self.proof.write_text(json.dumps(proof(self.root, self.manifest, self.directory / 'moved' / 'bundle')))

    def verify(self, artifact=None, state=None, image=None):
        return handback.verify_artifact(self.directory, artifact or self.artifact, self.master, self.scene,
                                        state or self.state, image or self.image)

    def test_accepts_consistent_evidence(self):
        self.assertEqual(self.verify()['reload']['processId'], 200)

    def test_rejections(self):
        rebinding = copy.deepcopy(self.state)
        rebinding['inputRebinding']['plate']['sha256'] = '0' * 64
        unrebound = {k: v for k, v in self.state.items() if k != 'inputRebinding'}
        listed = dict(self.artifact, files=[{'path': 'bundle.json'}, {'path': self.manifest['members'][0]['path']}])
        captures = dict(self.artifact, capturedInputs=[])
        title = copy.deepcopy(self.image)
        title['effectiveAppearance']['half']['legendTitle'] = 'other'
        ranged = copy.deepcopy(self.image)
        ranged['effectiveAppearance']['half']['range'] = [0.0, 2.0]
        for label, arguments in {'rebinding digest': {'state': rebinding}, 'no rebinding': {'state': unrebound},
                                 'captured data listed': {'artifact': listed}, 'receipt captures': {'artifact': captures},
                                 'legend title': {'image': title}, 'range': {'image': ranged},
                                 'missing digest': {'artifact': dict(self.artifact, manifestSha256=None)}}.items():
            with self.subTest(label):
                self.assertEqual(code(self.verify, *[arguments.get(k) for k in ('artifact', 'state', 'image')])[0],
                                 'VERIFICATION_FAILED')

    def test_authored_option_readback_is_required(self):
        for label, properties in {'missing origin': CLIP[1:],
                                  'default origin': [{**CLIP[0], 'value': [0.0, 0.0, 0.0]}, *CLIP[1:]]}.items():
            with self.subTest(label):
                manifest = copy.deepcopy(self.manifest)
                manifest['pipeline']['half']['properties'] = properties
                (self.root / 'bundle.json').write_text(json.dumps(manifest))
                artifact = dict(self.artifact, manifestSha256=sha(self.root / 'bundle.json'))
                self.assertIn('authored', code(self.verify, artifact)[1])

    def resave(self, **change):
        """Rewrite the manifest and its matching reload proof as a native producer would."""
        manifest = dict(copy.deepcopy(self.manifest), **change)
        (self.root / 'bundle.json').write_text(json.dumps(manifest))
        evidence = proof(self.root, manifest, self.directory / 'moved' / 'bundle')
        evidence['viewTime'] = manifest['viewTime']
        self.proof.write_text(json.dumps(evidence))
        return dict(self.artifact, manifestSha256=sha(self.root / 'bundle.json'))

    def test_scene_and_time_bind_to_the_plan_and_image(self):
        self.assertEqual(self.verify(self.resave())['manifest']['time'], 0)
        moved = dict(copy.deepcopy(self.state), visit={**self.state['visit'], 'time': 5.0})
        image = dict(copy.deepcopy(self.image), viewTime=5.0)
        cases = {'wrong scene': ({'scene': 'other'}, None, None, 'scene'),
                 'self-consistent wrong time': ({'time': 5, 'viewTime': 5.0}, None, None, 'time'),
                 'wrong planned time': ({}, moved, None, 'time'),
                 'wrong image time': ({}, None, image, 'time'),
                 'wrong manifest viewTime': ({'viewTime': 5.0}, None, None, 'time')}
        for label, (change, state, picture, message) in cases.items():
            with self.subTest(label):
                fault = code(self.verify, self.resave(**change), state, picture)
                self.assertEqual(fault[0], 'VERIFICATION_FAILED')
                self.assertIn(message, fault[1])
        artifact = self.resave()
        for label, value in {'string': '0', 'boolean': False, 'null': None, 'nonfinite': float('nan')}.items():
            with self.subTest('malformed planned time', value=label):
                state = dict(copy.deepcopy(self.state), visit={**self.state['visit'], 'time': value})
                self.assertEqual(code(self.verify, artifact, state)[0], 'VERIFICATION_FAILED')
            with self.subTest('malformed image time', value=label):
                self.assertEqual(code(self.verify, artifact, None, dict(self.image, viewTime=value))[0],
                                 'VERIFICATION_FAILED')
        for label, arguments in {'no visit': {'state': {k: v for k, v in self.state.items() if k != 'visit'}},
                                 'no image time': {'image': {k: v for k, v in self.image.items()
                                                             if k != 'viewTime'}}}.items():
            with self.subTest(label):
                self.assertEqual(code(self.verify, artifact, arguments.get('state'), arguments.get('image'))[0],
                                 'VERIFICATION_FAILED')

    def test_missing_or_malformed_proof_fails_later_verification(self):
        self.proof.write_text('{"version": ')
        self.assertEqual(code(self.verify)[0], 'VERIFICATION_FAILED')
        self.proof.unlink()
        self.assertEqual(code(self.verify)[0], 'VERIFICATION_FAILED')


class Fake:
    """Minimal reader handle: publications read whatever file the reader is bound to."""

    def __init__(self):
        self.FileName = None

    def UpdatePipeline(self, time):
        pass

    def consume(self):
        return Path(self.FileName[0]).read_bytes()


class Capture(unittest.TestCase):
    """The real workflow_resources capture path, driven by the native capture/rebind step."""

    def setUp(self):
        from unittest import mock
        from schemaxis.adaptors.paraview import handback_native
        self.native = handback_native
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / 'inputs' / 'plate.vtp'
        self.source.parent.mkdir()
        self.source.write_bytes(b'<VTKFile type="PolyData"><PolyData/></VTKFile>')
        self.master, scenes, _ = plan(surface_document(self.source))
        self.scene = scenes[0]
        self.handles = {'plate': Fake(), 'half': Fake()}
        self.handles['plate'].FileName = [str(self.source)]
        self.state = {'effective': {'plate': {'files': [str(self.source)]}}, 'proxyIds': {'plate': '7', 'half': '9'},
                      'observations': {'plate': OBSERVATION, 'half': OBSERVATION}}
        patches = [mock.patch.object(handback_native, 'observe', lambda proxy: copy.deepcopy(OBSERVATION)),
                   mock.patch('schemaxis.adaptors.paraview.input_closure.document_type',
                              lambda path: 'PolyData')]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.bundle = self.directory / 'run' / '000000-editable-state-bundle'
        self.bundle.parent.mkdir()

    def capture(self):
        active = type('Active', (), {'handles': self.handles})()
        return self.native.capture_inputs(active, self.master, self.scene, {'time': 0}, self.state, self.bundle)

    def test_stable_input_is_pinned_and_consumed_before_publication(self):
        original = self.source.read_bytes()
        rebinding = self.capture()
        captured = self.bundle / 'data' / 'plate' / 'data' / 'plate.vtp'
        self.assertEqual(self.handles['plate'].FileName, [str(captured)])
        self.assertEqual(rebinding['plate']['origin'], str(self.source))
        self.assertEqual(rebinding['plate']['sha256'], hashlib.sha256(original).hexdigest())
        self.assertTrue((self.bundle / 'data' / 'plate' / 'resource.json').is_file())
        # The image consumes the pinned copy, not the origin.
        self.assertEqual(self.handles['plate'].consume(), original)
        self.state['inputRebinding'] = rebinding
        members = self.native.verify_captures(self.bundle, self.state)
        self.assertEqual(members[0]['path'], 'data/plate/data/plate.vtp')
        self.assertEqual(self.state['effective']['plate']['files'], [str(self.source)])

    def test_origin_change_after_render_is_detected_even_with_equal_summary(self):
        self.state['inputRebinding'] = self.capture()
        rendered = self.handles['plate'].consume()
        # Same size and identical observations, different bytes: summaries cannot tell.
        self.source.write_bytes(rendered.replace(b'PolyData/', b'PolyDatb/'))
        self.assertEqual(code(self.native.verify_captures, self.bundle, self.state)[0], 'INPUT_CHANGED')

    def test_captured_copy_change_after_render_is_detected(self):
        self.state['inputRebinding'] = self.capture()
        copied = self.bundle / 'data' / 'plate' / 'data' / 'plate.vtp'
        copied.write_bytes(copied.read_bytes().replace(b'PolyData/', b'PolyDatb/'))
        self.assertEqual(code(self.native.verify_captures, self.bundle, self.state)[0], 'VERIFICATION_FAILED')

    def test_growth_and_replacement_during_capture_are_refused(self):
        from unittest import mock
        from schemaxis import workflow_resources as resources
        real = resources._open_read
        for label in ('growth', 'replacement'):
            with self.subTest(label):
                self.setUp()
                def racing(path, label=label):
                    if Path(path) == self.source:
                        if label == 'growth':
                            with open(self.source, 'ab') as stream:
                                stream.write(b'<!-- appended -->')
                        else:
                            replacement = self.source.with_name('replacement.vtp')
                            replacement.write_bytes(self.source.read_bytes())
                            os.replace(replacement, self.source)
                    return real(path)
                with mock.patch.object(resources, '_open_read', racing):
                    self.assertEqual(code(self.capture)[0], 'INPUT_CHANGED')
                self.assertFalse((self.bundle / 'data' / 'plate' / 'resource.json').exists())
                self.assertEqual(self.handles['plate'].FileName, [str(self.source)])

    def test_symlink_ancestor_and_oversized_input_are_refused_before_reading(self):
        from unittest import mock
        from schemaxis import workflow_resources as resources
        alias = self.directory / 'alias'
        alias.symlink_to(self.source.parent)
        linked = alias / 'plate.vtp'
        self.state['effective']['plate']['files'] = [str(linked)]
        with mock.patch.object(resources, '_open_read', side_effect=AssertionError('read')) as opened:
            self.assertEqual(code(self.capture)[0], 'UNSUPPORTED_STATE_BUNDLE')
            self.assertFalse(opened.called)
        self.setUp()
        with mock.patch.dict(handback.LIMITS, fileBytes=8), \
                mock.patch.object(resources, '_open_read', side_effect=AssertionError('read')) as opened:
            self.assertEqual(code(self.capture)[0], 'UNSUPPORTED_STATE_BUNDLE')
            self.assertFalse(opened.called)

    def test_native_run_captures_before_any_publication(self):
        source = (ROOT / 'src' / 'schemaxis' / 'adaptors' / 'paraview' / 'native_run.py').read_text()
        captured = source.index('capture_inputs(active')
        for consumer in ('geometry(backend', 'measurement(backend', 'publish(backend', 'renderer.prepare(',
                         'renderer.write(', 'save_bundle('):
            self.assertLess(captured, source.index(consumer), consumer)


if __name__ == '__main__':
    unittest.main()
