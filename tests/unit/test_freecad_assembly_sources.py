# Copyright (C) 2026 David L F Gaden
"""Host contracts for assemblies of verified phase-one parts at named mounts.

Producers here are synthetic, receipt-consistent run directories. They prove the
planner's admission, refusals and analytic oracle; native behaviour is qualified
separately by tools/qualify_freecad_assembly_sources.py.
"""
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad import assembly_sources as sources
from schemaxis.adaptors.freecad.assembly import plan, run, schema, reusableInputs
from schemaxis.adaptors.freecad import gui_state

ROOT = Path(__file__).resolve().parents[2]
AUXILIARIES = {'container': ('Origin', 'App::Origin'), 'X_Axis': ('X_Axis', 'App::Line'), 'Y_Axis': ('Y_Axis', 'App::Line'),
               'Z_Axis': ('Z_Axis', 'App::Line'), 'XY_Plane': ('XY_Plane', 'App::Plane'), 'XZ_Plane': ('XZ_Plane', 'App::Plane'),
               'YZ_Plane': ('YZ_Plane', 'App::Plane'), 'Origin': ('Origin001', 'App::Point')}


def part_document(width=80, thickness=5, height=50):
    doc = json.loads((ROOT/'examples/schemaxis/freecad-part-design.json').read_text())
    doc['parameters']['width'].update(value=width)
    doc['parameters']['thickness'].update(value=thickness)
    doc['nodes'][1]['options']['height'] = height
    return doc


FIXTURES = ROOT/'tests/fixtures/freecad-assembly-sources'


def producer(directory, authored=None, *, volume=None, mutate=None, data=None, fixture='plate.FCStd'):
    """A verified part run around real phase-one FCStd bytes, with receipts refreshed for those bytes.

    The fixture bytes were produced by this adaptor from synthetic inputs. Mutated `data` gets
    receipts refreshed exactly as an attacker could, so only content checks can refuse it.
    """
    from schemaxis.adaptors.freecad.adaptor import _native_plan
    directory = Path(directory)
    directory.mkdir(parents=True)
    authored = authored or part_document()
    prepared = _native_plan(authored)
    path = directory/'model.FCStd'
    path.write_bytes(data if data is not None else (FIXTURES/fixture).read_bytes())
    width = prepared['parameters']['width']['value'] if 'parameters' in prepared else 80
    thickness = prepared['parameters']['thickness']['value'] if 'parameters' in prepared else 5
    height = prepared['nodes'][1]['options']['height']
    artifacts = [{'file': str(directory/'model.step'), 'kind': 'cad', 'units': 'mm'},
                 {'file': str(directory/'model.stl'), 'kind': 'geometry', 'units': 'mm'},
                 {'file': str(path), 'kind': 'cadScene', 'units': 'mm', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
    receipt = {'status': 'succeeded', 'units': 'mm', 'definition': prepared, 'artifacts': artifacts,
               'native': {'valid': True, 'solids': 1, 'volume': volume or width*height*thickness, 'area': 1000.0,
                          'bounds': [-width/2, width/2, -height/2, height/2, 0.0, thickness]},
               'partDesignObservations': {'auxiliaries': {k: {'name': n, 'type': t} for k, (n, t) in AUXILIARIES.items()}}}
    if mutate:
        mutate(receipt)
    for name, value in (('authored.json', authored), ('plan.json', prepared), ('verification.json', receipt),
                        ('result.json', {'verified': True, 'status': 'succeeded'})):
        (directory/name).write_text(json.dumps(value))
    return path


def spacer_document():
    doc = part_document(width=60, thickness=12, height=40)
    doc['parameters']['width'].update(minimum=40, maximum=90)
    doc['parameters']['boreRadius'].update(value=4)
    doc['nodes'][3]['options']['centre'] = [-10, 5]
    return doc


def literal_document():
    return {'version': 'schemaxis.freecad/1', 'output': 'finished', 'nodes': [
        {'id': 'part', 'filter': 'body'},
        {'id': 'outline', 'filter': 'rectangle', 'inputs': {'body': 'part'}, 'options': {'width': 50, 'height': 30, 'plane': 'XY'}},
        {'id': 'slab', 'filter': 'pad', 'inputs': {'body': 'part', 'profile': 'outline'}, 'options': {'length': 8}},
        {'id': 'bore', 'filter': 'circle', 'inputs': {'body': 'part'}, 'options': {'radius': 2, 'plane': 'XY'}},
        {'id': 'finished', 'filter': 'pocket', 'inputs': {'base': 'slab', 'profile': 'bore'}, 'options': {'extent': 'throughAll'}}]}


def rezip(data, *, document=None, gui=None, add=(), drop=(), replace=None):
    """Return FCStd bytes with inert, byte-level edits (no executable payloads)."""
    import io
    source, target = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        for info in source.infolist():
            if info.filename in drop:
                continue
            content = source.read(info)
            if info.filename == 'Document.xml' and document:
                content = document(content.decode()).encode()
            if info.filename == 'GuiDocument.xml' and gui:
                content = gui(content.decode()).encode()
            if replace and info.filename in replace:
                content = replace[info.filename](content)
            archive.writestr(info.filename, content)
        for name, content in add:
            archive.writestr(name, content)
    return target.getvalue()


def in_object(text, name, old, new):
    start = text.index('<Object name="%s"' % name, text.index('<ObjectData'))
    stop = text.index('</Object>', start)
    assert old in text[start:stop], (name, old)
    return text[:start]+text[start:stop].replace(old, new, 1)+text[stop:]


def assembly(plate, spacer, **changes):
    doc = {'version': 'schemaxis.freecad.assembly/1', 'units': 'mm',
           'parts': [{'id': 'plate', 'source': str(plate), 'mounts': {
                         'bottom': {}, 'top': {'position': [0, 0, {'terms': {'thickness': 1}}]},
                         'side': {'position': [{'terms': {'width': 0.5}}, 0, {'terms': {'thickness': 0.5}}], 'z': '+X', 'x': '-Z'}}},
                     {'id': 'spacer', 'source': str(spacer), 'mounts': {
                         'bottom': {}, 'top': {'position': [0, 0, {'terms': {'thickness': 1}}]}}}],
           'components': [{'id': 'base', 'part': 'plate', 'position': [10, 20, 0], 'rotation': 30},
                          {'id': 'spacer', 'part': 'spacer'}, {'id': 'cover', 'part': 'plate'}],
           'grounded': 'base',
           'joints': [{'id': 'baseToSpacer', 'type': 'fixed', 'parent': {'component': 'base', 'mount': 'top'},
                       'child': {'component': 'spacer', 'mount': 'bottom'}, 'offset': [5, 0, 0], 'clocking': 90},
                      {'id': 'spacerToCover', 'type': 'fixed', 'parent': {'component': 'spacer', 'mount': 'top'},
                       'child': {'component': 'cover', 'mount': 'side'}, 'offset': [0, 0, 2]}]}
    doc.update(changes)
    return doc


class SourcedAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plate = producer(self.root/'plate')
        self.spacer = producer(self.root/'spacer', spacer_document(), fixture='spacer.FCStd')

    def tearDown(self):
        self.tmp.cleanup()

    def fault(self, document):
        with self.assertRaises(SchemaxisError) as caught:
            plan(document)
        return caught.exception.fault.code

    def test_host_safe_imports(self):
        subprocess.run([sys.executable, '-c', 'import sys; from schemaxis.adaptors.freecad import assembly_sources, '
                        'assembly_sources_saved, assembly_sources_native; '
                        'assert not any(n in sys.modules for n in ("FreeCAD","Part","AssemblyApp","JointObject","FreeCADGui"))'],
                       check=True, env={**os.environ, 'PYTHONPATH': str(ROOT/'src')})

    def test_constructor_plans_are_unchanged(self):
        demo = plan(json.loads((ROOT/'examples/schemaxis/freecad-assembly.json').read_text()))
        self.assertNotIn('sourced', demo)
        self.assertEqual(demo['parts'][0]['type'], 'box')

    def test_independent_rigid_transforms(self):
        prepared = plan(assembly(self.plate, self.spacer))
        poses = {k: v['matrix'] for k, v in prepared['expected']['components'].items()}
        s, c = 0.5, math.sqrt(3)/2
        self.assertTrue(sources.close(poses['base'], [c, -s, 0, 10, s, c, 0, 20, 0, 0, 1, 0, 0, 0, 0, 1]))
        # Spacer: base top (z=5), +5 mm along base x, clocked 90 degrees.
        self.assertTrue(sources.close(poses['spacer'], [-s, -c, 0, 10+5*c, c, -s, 0, 20+5*s, 0, 0, 1, 5, 0, 0, 0, 1]))
        # Cover: side mount (+Z along part +X) seated 2 mm above the spacer top (z=5+12).
        cover = poses['cover']
        self.assertTrue(sources.close([cover[8], cover[9], cover[10]], [1, 0, 0]))
        self.assertAlmostEqual(cover[11], 5+12+2-40)
        self.assertEqual({v['boundsMode'] for v in prepared['expected']['components'].values()}, {'containment'})
        self.assertEqual(prepared['native']['mounts']['plate.side'], 'Mount0_1')
        self.assertEqual(prepared['parts'][0]['mounts'][1]['value'], [40.0, 0.0, 2.5])

    def test_quarter_turns_keep_exact_bounds(self):
        doc = assembly(self.plate, self.spacer)
        doc['components'][0]['rotation'] = 90
        prepared = plan(doc)
        modes = {k: v['boundsMode'] for k, v in prepared['expected']['components'].items()}
        self.assertEqual(modes, {'base': 'exact', 'spacer': 'exact', 'cover': 'exact'})
        self.assertTrue(sources.close(prepared['expected']['components']['base']['bounds'], [-15, 35, -20, 60, 0, 5]))

    def test_rotated_corner_pocket_bounds_are_containment_only(self):
        """A pocket may cut the support corners: rotated local boxes only bound the part."""
        wanted = {'boundsMode': 'containment', 'bounds': [-10, 10, -10, 10, 0, 5]}
        inside = [-8, 9.5, -10, 7, 0, 5]          # a cut corner leaves the part strictly inside
        self.assertTrue(sources.bounds_agree(wanted, inside))
        self.assertFalse(sources.bounds_agree(wanted, [-10.1, 10, -10, 10, 0, 5]))
        self.assertFalse(sources.bounds_agree({**wanted, 'boundsMode': 'exact'}, inside))
        self.assertFalse(sources.bounds_agree(wanted, [1, 0, 0, 1, 0, 1]))

    def test_mount_and_joint_refusals(self):
        cases = {
            'UNSUPPORTED_PART': lambda d: d['parts'].append({'id': 'box', 'type': 'box'}),
            'UNSUPPORTED_FACE': lambda d: d['joints'][0].update(parent={'component': 'base', 'face': 'top'}),
            'UNKNOWN_MOUNT': lambda d: d['joints'][0]['child'].update(mount='side'),
            'INVALID_BINDING': lambda d: d['parts'][1]['mounts']['top'].update(position=[0, 0, {'terms': {'boreRadius': 1, 'other': 1}}]),
            'UNOBSERVABLE_BINDING': lambda d: d['parts'][0]['mounts']['top'].update(position=[0, 0, {'terms': {'thickness': 1e-12}}]),
            'INVALID_MOUNT': lambda d: d['parts'][0]['mounts']['side'].update(x='+X'),
        }
        for code, change in cases.items():
            doc = assembly(self.plate, self.spacer)
            change(doc)
            with self.subTest(code=code):
                self.assertEqual(self.fault(doc), code)
        more = [lambda d: d['parts'][0]['mounts']['side'].pop('x'),
                lambda d: d['parts'][0]['mounts'].update(outline={}),
                lambda d: d['parts'][0]['mounts']['top'].update(position=[0, 0, 200000]),
                lambda d: d['parts'][0]['mounts']['top'].update(position=[0, 0, {'terms': {'thickness': 1}, 'offset': 100000}])]
        for change in more:
            doc = assembly(self.plate, self.spacer)
            change(doc)
            self.assertIn(self.fault(doc), ('INVALID_MOUNT', 'INVALID_BINDING'))
        for change, code in ((lambda d: d['components'][1].update(id='Origin002'), 'DUPLICATE_COMPONENT'),
                             (lambda d: d['joints'][0].update(id='base'), 'DUPLICATE_JOINT'),
                             (lambda d: d['joints'][0].update(clocking=361), 'INVALID_ARGUMENT'),
                             (lambda d: d['joints'][0].update(type='revolute'), 'UNSUPPORTED_JOINT'),
                             (lambda d: d['joints'].append(dict(d['joints'][1], id='loop')), 'INVALID_JOINT_TREE')):
            doc = assembly(self.plate, self.spacer)
            change(doc)
            if code == 'DUPLICATE_COMPONENT':
                doc['joints'][0]['child']['component'] = 'Origin002'
                doc['joints'][1]['parent']['component'] = 'Origin002'
            with self.subTest(code=code):
                self.assertNotEqual(self.fault(doc), None)
                if code != 'INVALID_ARGUMENT':
                    self.assertEqual(self.fault(doc), code)

    def test_source_admission_refusals(self):
        def variant(name, **kwargs):
            return producer(self.root/name, **kwargs)
        cases = {
            'RESOURCE_NOT_FOUND': str(self.root/'absent/model.FCStd'),
            'route': str(variant('route', mutate=lambda r: r.update(units='m'))),
            'index': str(variant('index', mutate=lambda r: r['artifacts'].insert(0, r['artifacts'].pop()))),
            'unverified': str(variant('unverified', mutate=lambda r: r['native'].update(solids=2))),
        }
        for label, source in cases.items():
            doc = assembly(source, self.spacer)
            with self.subTest(label=label):
                self.assertIn(self.fault(doc), ('RESOURCE_NOT_FOUND', 'UNSUPPORTED_SOURCE'))
        wrong_name = self.root/'renamed'
        wrong_name.mkdir()
        (wrong_name/'part.FCStd').write_bytes(self.plate.read_bytes())
        self.assertEqual(self.fault(assembly(wrong_name/'part.FCStd', self.spacer)), 'UNSUPPORTED_SOURCE')
        link = self.root/'linked'
        os.symlink(self.plate.parent, link)
        self.assertEqual(self.fault(assembly(link/'model.FCStd', self.spacer)), 'UNSUPPORTED_SOURCE')
        legacy = json.loads((ROOT/'examples/schemaxis/freecad-bracket.json').read_text())
        self.assertEqual(self.fault(assembly(variant('legacy', authored=legacy), self.spacer)), 'UNSUPPORTED_SOURCE')
        studied = self.root/'assembled'
        producer(studied)
        (studied/'authored.json').write_text(json.dumps({'version': 'schemaxis.freecad.assembly/1'}))
        self.assertEqual(self.fault(assembly(studied/'model.FCStd', self.spacer)), 'UNSUPPORTED_SOURCE')
        malformed = self.root/'malformed'
        producer(malformed)
        (malformed/'model.FCStd').write_bytes(b'not a zip')
        self.assertEqual(self.fault(assembly(malformed/'model.FCStd', self.spacer)), 'UNSUPPORTED_SOURCE')
        for label, members in (('duplicate', [('Document.xml', '<a/>'), ('Document.xml', '<b/>')]),
                               ('escape', [('Document.xml', '<a/>'), ('../outside', 'x')])):
            path = producer(self.root/label)
            with zipfile.ZipFile(path, 'w') as archive:
                for member, data in members:
                    archive.writestr(member, data)
            with self.subTest(label=label):
                self.assertEqual(self.fault(assembly(path, self.spacer)), 'UNSUPPORTED_SOURCE')

    def test_values_the_saved_document_cannot_store_are_refused_at_admission(self):
        from schemaxis.adaptors.freecad.adaptor import _native_plan
        from schemaxis.adaptors.freecad.assembly_sources import _saved_exactly
        # The phase-one precision-pad producers: recompute regenerates different history bytes.
        precise = part_document()
        precise['nodes'][2]['drive']['length'] = {'terms': {'thickness': 0.12345678901234566}, 'offset': 2.1234567890123457}
        self.assertEqual(_saved_exactly(_native_plan(precise)), ['slab.length (expression)'])
        source = producer(self.root/'precise', precise)
        with self.assertRaises(SchemaxisError) as caught:
            plan(assembly(source, self.spacer))
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_SOURCE')
        self.assertIn('cannot store exactly', caught.exception.fault.message)
        self.assertEqual(caught.exception.fault.location, 'plate.source')
        # Fifteen significant digits round-trip through the saved expression and length.
        stored = part_document(width=80.123456789012)
        stored['nodes'][2]['drive']['length'] = {'terms': {'thickness': 0.123456789012345}, 'offset': 2.12345678901234}
        self.assertEqual(_saved_exactly(_native_plan(stored)), [])
        self.assertEqual(_saved_exactly(_native_plan(part_document())), [])

    def test_changed_source_bytes_invalidate(self):
        doc = assembly(self.plate, self.spacer)
        before = reusableInputs(doc)
        self.assertEqual(set(before), {str(self.plate), str(self.spacer)})
        with zipfile.ZipFile(self.plate, 'a') as archive:
            archive.writestr('extra.txt', 'changed')
        self.assertEqual(self.fault(doc), 'INPUT_CHANGED')

    def test_gui_inspection_cannot_run_before_complete_host_admission(self):
        from unittest.mock import patch
        from schemaxis.errors import fail
        target = self.root/'out'
        with patch('schemaxis.adaptors.freecad.process.SubprocessRunner',WholeRunDeadlineTests.Runner), \
             patch('schemaxis.adaptors.freecad.adaptor.verify',return_value={'verified':True}), \
             patch.object(sources,'check_captured'), \
             patch.object(sources,'verify',side_effect=lambda *a,**k:fail('VERIFICATION_FAILED','withheld complete admission')), \
             patch('schemaxis.adaptors.freecad.assembly_sources_gui.inspect_verified') as gui:
            with self.assertRaises(SchemaxisError) as caught:
                sources.run(assembly(self.plate, self.spacer), plan(assembly(self.plate, self.spacer)), target,
                            executable='/bin/true', timeout=10, gui_executable='/bin/true')
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            gui.assert_not_called()
        self.assertEqual(json.loads((target/'result.json').read_text())['status'],'failed')

    def test_schema_offers_mounts_and_clocking(self):
        contract = json.dumps(schema())
        for word in ('"source"', '"mounts"', '"mount"', '"clocking"', '"+X"'):
            self.assertIn(word, contract)

    def test_mount_expression_grammar_is_unit_qualified(self):
        prepared = plan(assembly(self.plate, self.spacer))
        part, mount = prepared['parts'][1], prepared['parts'][1]['mounts'][1]
        texts = sources.mount_expressions(part, mount, 'SchemaxisParameters001')
        self.assertEqual(texts, {'.AttachmentOffset.Base.z': '1 * SchemaxisParameters001.dim_thickness + 0 mm'})
        renames = {'spacer': {'SchemaxisParameters': 'SchemaxisParameters001'}}
        problems = []
        def require(ok, message, **detail):
            if not ok:
                problems.append(message)
        sources.check_mount_expressions(part, mount, renames, [['.AttachmentOffset.Base.z', texts['.AttachmentOffset.Base.z']]], require, 'k')
        self.assertEqual(problems, [])
        for wrong in ('12', '1 * SchemaxisParameters001.dim_thickness + 0', '1 * SchemaxisParameters.dim_thickness + 0 mm'):
            with self.subTest(wrong=wrong), self.assertRaises(SchemaxisError):
                sources.check_mount_expressions(part, mount, renames, [['.AttachmentOffset.Base.z', wrong]], require, 'k')


class LauncherSpy:
    """Stands in for the native process runner; any construction means a native launch."""
    calls = []

    def __init__(self, *args, **kwargs):
        LauncherSpy.calls.append(args)
        raise AssertionError('native launcher must not be reached')


INERT_PYTHON = ('<Property name="UnqualifiedState" type="App::PropertyPythonObject" status="1">'
                '<Python value="bnVsbA==" encoded="yes" module="not_an_importable_module" class="Inert"/></Property>')


class SourceEnvelopeTests(unittest.TestCase):
    """B1: a closed host envelope refuses unqualified source content before any native open."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.spacer = producer(self.root/'spacer', spacer_document(), fixture='spacer.FCStd')
        self.plate_bytes = (FIXTURES/'plate.FCStd').read_bytes()
        LauncherSpy.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def refuse(self, label, data):
        """Receipts are refreshed for the mutated bytes; planning and running must still refuse."""
        source = producer(self.root/label, data=data)
        doc = assembly(source, self.spacer)
        with self.assertRaises(SchemaxisError) as planned:
            plan(doc)
        from unittest import mock
        with mock.patch('schemaxis.adaptors.freecad.process.SubprocessRunner', LauncherSpy), self.assertRaises(SchemaxisError) as ran:
            run(doc, self.root/(label+'-run'), executable='/bin/true', timeout=30)
        self.assertEqual(LauncherSpy.calls, [], label)
        return planned.exception.fault.code, ran.exception.fault.code

    def test_valid_parameterised_and_literal_sources_are_admitted(self):
        prepared = plan(assembly(producer(self.root/'plate', data=self.plate_bytes), self.spacer))
        self.assertEqual([p['source']['expandedBytes'] > 0 for p in prepared['parts']], [True, True])
        block = producer(self.root/'block', literal_document(), fixture='block.FCStd')
        doc = assembly(block, self.spacer)
        doc['parts'][0]['mounts'] = {'top': {'position': [0, 0, 8]}, 'side': {'position': [25, 0, 4], 'z': '+X', 'x': '-Z'}}
        self.assertIsNone(plan(doc)['parts'][0]['source']['varset'])

    def test_unqualified_state_is_refused_before_native_launch(self):
        doc = lambda edit: rezip(self.plate_bytes, document=edit)  # noqa: E731
        body_props = '<Properties Count="12" TransientCount="2">'
        cases = {
            'inert-python-property': doc(lambda t: in_object(t, 'N0', body_props, body_props+INERT_PYTHON)),
            'external-file-link': doc(lambda t: in_object(t, 'N0', body_props, body_props+'<Property name="External" '
                'type="App::PropertyXLink"><XLink file="elsewhere.FCStd" stamp="" name="Body"/></Property>')),
            'dynamic-property': doc(lambda t: in_object(t, 'N0', body_props, body_props+'<Property name="Note" type="App::PropertyString" '
                'group="Base" doc="" attr="0" ro="0" hide="0" status="1"><String value="x"/></Property>')),
            'unknown-extension': doc(lambda t: in_object(t, 'N0', '</Extensions>', '<Extension type="App::LinkBaseExtension" '
                'name="LinkBaseExtension"></Extension></Extensions>')),
            'doctype-entity': doc(lambda t: t.replace("<?xml version='1.0' encoding='utf-8'?>\n",
                "<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE Document [<!ENTITY inert \"x\">]>\n", 1)),
            'cross-document-expression': doc(lambda t: t.replace('1 * SchemaxisParameters.dim_thickness + 0 mm',
                                                                 '1 * other#SchemaxisParameters.dim_thickness + 0 mm', 1)),
            'foreign-reference': doc(lambda t: in_object(t, 'N0', '<Link value="N4"/>', '<Link value="Assembly"/>')),
            'gui-python-proxy': rezip(self.plate_bytes, gui=lambda t: t.replace(
                '<Bool value="true" /></Property></Properties>', '<Bool value="true" /></Property>'
                '<Property name="Proxy" type="App::PropertyPythonObject"><Python value="bnVsbA==" encoded="yes" '
                'module="not_an_importable_module" class="Inert"/></Property></Properties>', 1)),
            'extra-member': rezip(self.plate_bytes, add=[('inert-note.txt', 'inert')]),
            'missing-member': rezip(self.plate_bytes, drop=['N2.Shape.brp']),
            'corrupt-brep': rezip(self.plate_bytes, replace={'N2.Shape.brp': lambda b: b'not a BREP payload\n'}),
            'truncated-brep': rezip(self.plate_bytes, replace={'N4.Shape.brp': lambda b: b[:len(b)//2]}),
            'corrupt-element-map': rezip(self.plate_bytes, replace={'N4.Shape.Map.txt': lambda b: b.replace(b'EndMap', b'Endmap', 1)}),
            'element-map-foreign-tag': rezip(self.plate_bytes, replace={'N4.Shape.Map.txt': lambda b: re.sub(rb';:H[0-9a-f]+', b';:Hfffff', b, 1)}),
            'escaping-member': rezip(self.plate_bytes, add=[('../outside.txt', 'x')]),
            'sub-element-reference': doc(lambda t: in_object(t, 'N1', 'sub=""', 'sub="Face1"')),
        }
        for label, data in cases.items():
            with self.subTest(label=label):
                self.assertNotEqual(data, self.plate_bytes, label)
                planned, ran = self.refuse(label, data)
                self.assertIn(planned, ('UNSUPPORTED_SOURCE',), label)
                self.assertIn(ran, ('UNSUPPORTED_SOURCE',), label)

    def test_generation1_sparse_string_references_bind_actual_ids_not_entry_count(self):
        from schemaxis.adaptors.freecad.source_envelope import string_ids,HASH_REFERENCE
        import io
        with zipfile.ZipFile(io.BytesIO(self.plate_bytes)) as z:
            table=z.read('StringHasher.Table.txt')
            map_name=next(n for n in z.namelist() if n.endswith('.Map.txt') and HASH_REFERENCE.search(z.read(n)))
            mapped=z.read(map_name)
        known=string_ids(table,'fixture','UNSUPPORTED_SOURCE','table');high=max(known)+32
        count=len(known)+1;missing=next(i for i in range(1,count+1) if i not in known)
        self.assertNotEqual(missing,high)
        extended=re.sub(rb'StringTableStart v1 [0-9]+',b'StringTableStart v1 '+str(count).encode(),table,count=1)
        extended+=b'-20.0 0:sparse_saved_record\n'
        self.assertEqual(string_ids(extended,'fixture','UNSUPPORTED_SOURCE','table'),known|{high})
        token=HASH_REFERENCE.search(mapped)
        def changed(identity):return mapped[:token.start()]+b'#'+format(identity,'x').encode()+mapped[token.end():]
        admitted=rezip(self.plate_bytes,replace={'StringHasher.Table.txt':lambda b:extended,map_name:lambda b:changed(high)})
        path=producer(self.root/'sparse',data=admitted)
        self.assertEqual(sources.admit(str(path),'sparse').get('generation',1),1)
        # This low ID is <= entry count but absent from the actual table. The
        # old count-range predicate admitted it; decode must refuse prelaunch.
        missing_data=rezip(self.plate_bytes,replace={'StringHasher.Table.txt':lambda b:extended,map_name:lambda b:changed(missing)})
        self.assertEqual(self.refuse('missing-low-sid',missing_data),('UNSUPPORTED_SOURCE','UNSUPPORTED_SOURCE'))
        duplicate=extended+b'-0.0 0:duplicate\n'
        duplicate=re.sub(rb'StringTableStart v1 [0-9]+',b'StringTableStart v1 '+str(count+1).encode(),duplicate,count=1)
        duplicate_data=rezip(self.plate_bytes,replace={'StringHasher.Table.txt':lambda b:duplicate})
        self.assertEqual(self.refuse('duplicate-sid',duplicate_data),('UNSUPPORTED_SOURCE','UNSUPPORTED_SOURCE'))

    def test_object_id_corruption_is_refused_before_native_launch(self):
        def change(text,value):
            if value=='duplicate':
                value=re.search(r'<Object\b[^>]*name="N0"[^>]*id="([0-9]+)"',text)[1]
            return re.sub(r'(<Object\b[^>]*name="Origin001"[^>]*id=")[^"]+',
                          lambda match:match[1]+value,text,count=1)
        for value in ['duplicate','0','-1','01','+1',str(2**63)]:
            with self.subTest(value=value):
                data=rezip(self.plate_bytes,document=lambda text:change(text,value))
                self.assertNotEqual(data,self.plate_bytes)
                self.assertEqual(self.refuse('bad-id-'+value.replace('+','plus'),data),
                                 ('UNSUPPORTED_SOURCE','UNSUPPORTED_SOURCE'))

    def test_retained_bytes_are_guarded_immediately_before_launch(self):
        from unittest import mock
        plate = producer(self.root/'plate', data=self.plate_bytes)
        doc = assembly(plate, self.spacer)
        target = self.root/'guarded'
        import schemaxis.artifacts as artifacts
        original = artifacts.runtime_archive

        def tamper_then_archive():
            retained = target/'sources'/'source0.FCStd'
            retained.write_bytes(rezip(retained.read_bytes(), document=lambda t: in_object(
                t, 'N0', '<Properties Count="12" TransientCount="2">', '<Properties Count="12" TransientCount="2">'+INERT_PYTHON)))
            return original()
        with mock.patch('schemaxis.adaptors.freecad.process.SubprocessRunner', LauncherSpy), \
                mock.patch('schemaxis.adaptors.freecad.adaptor.verify', lambda *a, **k: {'verified': True}), \
                mock.patch('schemaxis.artifacts.runtime_archive', tamper_then_archive), \
                self.assertRaises(SchemaxisError) as caught:
            sources.run(doc, plan(doc), target, executable='/bin/true', timeout=30)
        self.assertEqual(caught.exception.fault.code, 'INPUT_CHANGED')
        self.assertEqual(LauncherSpy.calls, [])
        with self.assertRaises(SchemaxisError) as guarded:
            sources.guard_retained(plan(doc), target, 'UNSUPPORTED_SOURCE')
        self.assertEqual(guarded.exception.fault.code, 'INPUT_CHANGED')

    def test_cumulative_source_budget(self):
        from unittest import mock
        with mock.patch.object(sources, 'TOTAL_EXPANDED_BYTES', 150000):
            self.assertEqual(SourcedAssemblyTests.fault(self, assembly(producer(self.root/'plate', data=self.plate_bytes), self.spacer)),
                             'ASSEMBLY_LIMIT')


class PayloadBindingTests(unittest.TestCase):
    """Legacy B2 fixture: strict direct payload binding without a new replay contract."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        plate = producer(self.root/'plate')
        spacer = producer(self.root/'spacer', spacer_document(), fixture='spacer.FCStd')
        doc = json.loads((FIXTURES/'assembly.json').read_text())
        doc['parts'][0]['source'], doc['parts'][1]['source'] = str(plate), str(spacer)
        self.prepared = plan(doc)
        # This historical assembly fixture predates captured bodyHistory. Keep
        # exercising its unchanged legacy direct binder; new typed Body copies
        # require full regeneration (independently tested in bridge/native gates).
        for part in self.prepared['parts']:
            part['source'].pop('bodyHistory',None);part['source'].pop('sourceFrame',None)
        self.renames = json.loads((FIXTURES/'renames.json').read_text())
        self.retained = {'plate': plate, 'spacer': spacer}
        self.data = (FIXTURES/'assembly.FCStd').read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, data):
        from schemaxis.adaptors.freecad.assembly_sources_saved import verify_saved
        path = self.root/'candidate.FCStd'
        path.write_bytes(data)
        verify_saved(self.prepared, path, self.renames, self.retained)

    def test_genuine_assembly_is_bound_including_signed_zero_spelling(self):
        from schemaxis.adaptors.freecad.assembly_payloads import same_brep
        self.check(self.data)
        assembly_zip, plate_zip = zipfile.ZipFile(FIXTURES/'assembly.FCStd'), zipfile.ZipFile(FIXTURES/'plate.FCStd')
        differing = [n for n in plate_zip.namelist() if n.endswith('.brp') and plate_zip.read(n) != assembly_zip.read(n)]
        self.assertTrue(differing, 'fixture must exercise the signed-zero equivalence')
        for name in differing:
            self.assertTrue(same_brep(plate_zip.read(name), assembly_zip.read(name)), name)
            self.assertIn(b'-0.0', plate_zip.read(name))

    def test_signed_zero_rule_is_lexical_and_narrow(self):
        from schemaxis.adaptors.freecad.assembly_payloads import same_brep
        line = b'1.000000000000000 -0.000000000000000 2.500000000000000 \n'
        self.assertTrue(same_brep(line, line.replace(b'-0.000000000000000', b'0.000000000000000')))
        for wrong in (line.replace(b'-0.000000000000000', b'0.000000000000001'),   # nonzero, near-equal
                      line.replace(b'2.500000000000000', b'2.500000000000001'),
                      line.replace(b'-0.000000000000000', b'-0.0'),                 # same float, other spelling
                      line.replace(b'-0.000000000000000', b'0.000000000000000 ')):
            self.assertFalse(same_brep(line, wrong), wrong)
        self.assertFalse(same_brep(line.replace(b'-0.0', b'0.0'), line))           # reverse direction

    def test_payload_substitution_corruption_and_membership_are_refused(self):
        brep = lambda b: b.replace(b'1.000000000000000', b'1.000000000000001', 1)  # noqa: E731
        swap_a, swap_b = zipfile.ZipFile(FIXTURES/'assembly.FCStd').read('N0.Shape.brp'), \
            zipfile.ZipFile(FIXTURES/'assembly.FCStd').read('N001.Shape.brp')

        def map_tag(b):
            own = re.search(rb';:H([0-9a-f]+)', b).group(1)
            return b.replace(b';:H'+own, b';:H15a', 1) if own != b'15a' else b.replace(b';:H'+own, b';:H168', 1)

        def map_child(b):
            return re.sub(rb'(ChildCount 1\n1 0 )(\d+)', lambda m: m.group(1)+str(int(m.group(2))+1).encode(), b, 1)

        def map_names(b):
            return b.replace(b'NameCount 5\n0\n', b'NameCount 4\n', 1)

        cases = {
            'corrupt-shape': rezip(self.data, replace={'N0.Shape.brp': lambda b: b'not a BREP payload'}),
            'near-equal-shape-number': rezip(self.data, replace={'N4.Shape.brp': brep}),
            'missing-shape': rezip(self.data, drop=['N0.Shape.brp']),
            'extra-member': rezip(self.data, add=[('inert-note.txt', 'inert')]),
            'duplicate-member': rezip(self.data, add=[('N0.Shape.brp', swap_a)]),
            'escaping-member': rezip(self.data, add=[('../outside.txt', 'x')]),
            'swapped-shapes-between-parts': rezip(self.data, replace={'N0.Shape.brp': lambda b: swap_b, 'N001.Shape.brp': lambda b: swap_a}),
            'history-payload-substituted': rezip(self.data, replace={'N2.Shape.brp': lambda b: swap_a}),
            'element-map-header': rezip(self.data, replace={'N0.Shape.Map.txt': lambda b: b'garbage'}),
            'element-map-other-part-tag': rezip(self.data, replace={'N005.Shape.Map.txt': map_tag}),
            'element-map-child-record': rezip(self.data, replace={'N0.Shape.Map.txt': map_child}),
            'element-map-skeleton': rezip(self.data, replace={'N002.Shape.Map.txt': map_names}),
            'element-map-swapped-between-parts': rezip(self.data, replace={'N4.Shape.Map.txt': lambda b: zipfile.ZipFile(
                FIXTURES/'assembly.FCStd').read('N005.Shape.Map.txt')}),
            'mount-datum-moved': rezip(self.data, replace={'Mount0_1.Shape.brp': lambda b: b.replace(b'0.000000000000000 \n',
                                                                                                    b'1.000000000000000 \n', 1)}),
            'link-list-not-empty': rezip(self.data, replace={'PlacementList1': lambda b: b'\x01\x00\x00\x00'}),
            'string-table-count': rezip(self.data, replace={'StringHasher.Table.txt': lambda b: b.replace(b'StringTableStart v1 ',
                                                                                                         b'StringTableStart v1 9', 1)}),
            'doctype': rezip(self.data, document=lambda t: t.replace("<?xml version='1.0' encoding='utf-8'?>\n",
                "<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE Document>\n", 1)),
        }
        for label, data in cases.items():
            with self.subTest(label=label):
                self.assertNotEqual(data, self.data, label)
                with self.assertRaises(SchemaxisError) as caught:
                    self.check(data)
                self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED', label)


def plate_vertices(slot):
    """80 x 50 x 6 plate with a centred rectangular through-slot (width, height)."""
    w, h = slot
    return sorted([float(x), float(y), float(z)] for z in (0.0, 6.0)
                  for x, y in ((-40, -25), (40, -25), (40, 25), (-40, 25), (-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)))


def rotated_hole_vertices():
    return plate_vertices((4, 10))


def solid_record(slot=(10, 4)):
    """Same summaries for slot (10, 4) and (4, 10): only vertex coordinates distinguish them."""
    return {'type': 'Solid', 'valid': True, 'counts': [1, 1, 10, 4, 24, 16], 'volume': 23760.0, 'area': 9648.0,
            'length': 712.0, 'bounds': [-40.0, 40.0, -25.0, 25.0, 0.0, 6.0], 'centreOfMass': [0.0, 0.0, 3.0],
            'vertices': plate_vertices(slot),
            'faces': sorted([['Plane', a] for a in (3960.0, 3960.0, 480.0, 480.0, 300.0, 300.0, 60.0, 60.0, 24.0, 24.0)]),
            'edges': sorted([['Line', l] for l in [80.0]*4 + [50.0]*4 + [10.0]*4 + [4.0]*4 + [6.0]*8])}


class HistoryRuleTests(unittest.TestCase):
    def test_representation_noise_is_accepted_and_rotated_hole_is_refused(self):
        stored = solid_record()
        noisy = copy.deepcopy(stored)
        noisy['volume'] += 10*math.ulp(noisy['volume'])
        noisy['vertices'] = [[x + 2*math.ulp(40.0) for x in p] for p in noisy['vertices']]
        noisy['edges'][0][1] += math.ulp(noisy['edges'][0][1])
        self.assertTrue(sources.same_history_shape(stored, noisy))
        rotated = solid_record((4, 10))
        self.assertEqual({k: v for k, v in stored.items() if k != 'vertices'}, {k: v for k, v in rotated.items() if k != 'vertices'})
        self.assertFalse(sources.same_history_shape(stored, rotated))
        far = copy.deepcopy(stored)
        far['vertices'][0][0] += 1e-9
        self.assertFalse(sources.same_history_shape(stored, far))
        swapped = copy.deepcopy(stored)
        swapped['faces'][0][0] = 'Cylinder'
        self.assertFalse(sources.same_history_shape(stored, swapped))


class CaptureHistoryTests(unittest.TestCase):
    def test_every_named_history_payload_must_be_reproduced_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            plate = producer(Path(tmp)/'plate')
            spacer = producer(Path(tmp)/'spacer', spacer_document(), fixture='spacer.FCStd')
            part = plan(assembly(plate, spacer))['parts'][0]
            names = ['N0.Shape', 'N1.InternalShape', 'N1.Shape', 'N2.AddSubShape', 'N2.Shape', 'N2.SuppressedShape',
                     'N3.InternalShape', 'N3.Shape', 'N4.AddSubShape', 'N4.Shape', 'N4.SuppressedShape']
            shape = solid_record()
            good = {'recomputeStates': {}, 'history': {'stored': {n: dict(shape) for n in names},
                                                       'recomputed': {n: dict(shape) for n in names}}}
            problems = []
            require = lambda ok, message, **d: None if ok else problems.append(message)  # noqa: E731
            sources.check_history(part, good, plate, require)
            self.assertEqual(problems, [])
            for change in (lambda r: r['history']['recomputed']['N2.Shape'].update(volume=19858.6001),
                           lambda r: r['history']['recomputed']['N4.AddSubShape'].update(counts=[1, 1, 7, 9, 18, 13]),
                           lambda r: r['history']['recomputed']['N0.Shape'].update(centreOfMass=[-0.1, -0.07, 2.5000001]),
                           lambda r: r['history']['recomputed']['N4.Shape'].update(vertices=rotated_hole_vertices()),
                           lambda r: r['history']['stored'].pop('N3.Shape'),
                           lambda r: r['history']['stored'].update({'N1.InternalShape': None}),
                           lambda r: r.update(recomputeStates={'N4': ['Invalid']})):
                broken = copy.deepcopy(good)
                change(broken)
                problems.clear()
                sources.check_history(part, broken, plate, require)
                self.assertTrue(problems)


class CaptureBeforeBuildTests(unittest.TestCase):
    def test_capture_history_is_checked_from_the_capture_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plate = producer(tmp/'plate')
            spacer = producer(tmp/'spacer', spacer_document(), fixture='spacer.FCStd')
            prepared = plan(assembly(plate, spacer))
            run_dir = tmp/'run'
            (run_dir/'sources').mkdir(parents=True)
            for part, source in (('plate', plate), ('spacer', spacer)):
                (run_dir/prepared['native']['retained'][part]).write_bytes(source.read_bytes())
            shape = solid_record()
            names = ['N0.Shape', 'N1.InternalShape', 'N1.Shape', 'N2.AddSubShape', 'N2.Shape', 'N2.SuppressedShape',
                     'N3.InternalShape', 'N3.Shape', 'N4.AddSubShape', 'N4.Shape', 'N4.SuppressedShape']
            record = {'recomputeStates': {}, 'history': {'stored': {n: dict(shape) for n in names},
                                                         'recomputed': {n: dict(shape) for n in names}}}
            capture = {'stage': 'capture', 'definition': prepared, 'parts': {'plate': copy.deepcopy(record), 'spacer': copy.deepcopy(record)}}
            (run_dir/'capture.json').write_text(json.dumps(capture))
            sources.check_captured(prepared, run_dir)
            capture['parts']['spacer']['history']['recomputed']['N2.Shape']['volume'] = 20000.0
            (run_dir/'capture.json').write_text(json.dumps(capture))
            with self.assertRaises(SchemaxisError) as caught:
                sources.check_captured(prepared, run_dir)
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')


class PlannerBoundaryTests(unittest.TestCase):
    """Malformed JSON types stay structured faults through the public registry route."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.doc = assembly(producer(root/'plate'), producer(root/'spacer', spacer_document(), fixture='spacer.FCStd'))

    def tearDown(self):
        self.tmp.cleanup()

    def plan_fault(self, document):
        from schemaxis.adaptors import registry
        with self.assertRaises(SchemaxisError) as caught:
            registry.plan(document, legacy=True)
        return caught.exception.fault

    def test_mount_axes_reject_arrays_objects_null_and_unknown_strings_at_their_location(self):
        from schemaxis.adaptors import registry
        registry.plan(self.doc, legacy=True)
        for mount, axis in (('top', 'z'), ('side', 'x'), ('side', 'z')):
            for value in ([], {}, None, 'up', ['+Z'], {'+Z': 1}):
                doc = copy.deepcopy(self.doc)
                doc['parts'][0]['mounts'][mount][axis] = value
                with self.subTest(mount=mount, axis=axis, value=value):
                    fault = self.plan_fault(doc)
                    self.assertEqual((fault.code, fault.location), ('INVALID_MOUNT', 'plate.mounts.%s.%s' % (mount, axis)))
        doc = copy.deepcopy(self.doc)
        doc['parts'][0]['mounts']['top'].update(z='-Z', x='-Y')
        self.assertEqual(registry.plan(doc, legacy=True)['parts'][0]['mounts'][2]['z'], '-Z')

    def test_every_authored_field_refuses_wrong_json_types_with_a_structured_fault(self):
        pointers = [('parts', 0, 'mounts', 'top', 'z'), ('parts', 0, 'mounts', 'side', 'x'), ('parts', 0, 'mounts', 'top', 'position'),
                    ('parts', 0, 'mounts', 'top', 'position', 2), ('parts', 0, 'mounts', 'top', 'position', 2, 'terms'),
                    ('parts', 0, 'mounts', 'top', 'position', 2, 'terms', 'thickness'), ('parts', 0, 'mounts', 'top', 'position', 2, 'offset'),
                    ('parts', 0, 'mounts', 'top'), ('parts', 0, 'mounts'), ('parts', 0, 'source'), ('parts', 0, 'id'),
                    ('joints', 0, 'parent', 'mount'), ('joints', 0, 'parent'), ('joints', 0, 'child', 'component'),
                    ('joints', 0, 'clocking'), ('joints', 0, 'offset'), ('components', 0, 'part'), ('components', 0, 'rotation'), ('grounded',)]
        for pointer in pointers:
            for value in ([], {}, None, True, 'up', [1, 2, 3]):
                doc = copy.deepcopy(self.doc)
                target = doc
                for key in pointer[:-1]:
                    target = target[key]
                target[pointer[-1]] = value
                with self.subTest(pointer=pointer, value=value):
                    from schemaxis.adaptors import registry
                    try:  # some values are valid; none may escape as an unstructured exception
                        registry.plan(doc, legacy=True)
                    except SchemaxisError:
                        pass


class WholeRunDeadlineTests(unittest.TestCase):
    """Contract level, mocked: the native runner, producer verification and final verification are stand-ins.

    Native timeout evidence is recorded separately by the owner's qualification; these tests prove only that the
    sourced route's whole-run deadline and cancellation also cover final host verification.
    """

    class Runner:
        launched = []

        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get('timeout')

        def __call__(self, source):
            WholeRunDeadlineTests.Runner.launched.append(self.timeout)
            from types import SimpleNamespace
            return SimpleNamespace(to_dict=lambda: {'standIn': True})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.doc = assembly(producer(self.root/'plate'), producer(self.root/'spacer', spacer_document(), fixture='spacer.FCStd'))
        self.prepared = plan(self.doc)
        WholeRunDeadlineTests.Runner.launched = []

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, target, final_verify, clock=None, cancelled=lambda: False,gui=False):
        from unittest import mock
        patches = [mock.patch('schemaxis.adaptors.freecad.process.SubprocessRunner', WholeRunDeadlineTests.Runner),
                   # This fixture isolates the outer serial-stage deadline;
                   # independent reconstruction has its own native controls.
                   mock.patch('schemaxis.adaptors.freecad.source_bridge.verify_before_open', lambda *a, **k: None),
                   mock.patch('schemaxis.dispatch.cancellation_requested', cancelled),
                   mock.patch('schemaxis.adaptors.freecad.adaptor.verify', lambda *a, **k: {'verified': True}),
                   mock.patch.object(sources, 'check_captured', lambda *a, **k: None),
                   mock.patch.object(sources, 'verify', final_verify)]
        if clock is not None:
            patches.append(mock.patch.object(sources.time, 'monotonic', clock))
        for item in patches:
            item.start()
        try:
            return sources.run(self.doc, self.prepared, target, executable='/bin/true', timeout=60,
                               gui_executable='/bin/true' if gui else None)
        finally:
            for item in reversed(patches):
                item.stop()

    def test_normal_path_still_succeeds(self):
        result = self.execute(self.root/'ok', lambda *a, **k: {'verified': True})
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(WholeRunDeadlineTests.Runner.launched), 3)
        self.assertEqual(json.loads((self.root/'ok'/'result.json').read_text())['status'], 'succeeded')

    def test_optional_gui_runs_after_admission_and_is_within_the_same_budget(self):
        from unittest.mock import patch
        events=[];now=[0.0]
        def verified(*a,**k):events.append('verified');return {'verified':True,'nativeSha256':'a'*64}
        def inspect(*a,**k):
            self.assertEqual(k['verified_sha256'],'a'*64)
            events.append('gui');return {'completed':True}
        with patch('schemaxis.adaptors.freecad.assembly_sources_gui.inspect_verified',inspect):
            result=self.execute(self.root/'gui-ok',verified,clock=lambda:now[0],gui=True)
        self.assertEqual(events,['verified','gui']);self.assertTrue(result['guiInspection']['completed'])
        def slow(*a,**k):now[0]=61;return {'completed':True}
        with patch('schemaxis.adaptors.freecad.assembly_sources_gui.inspect_verified',slow), self.assertRaises(SchemaxisError) as caught:
            self.execute(self.root/'gui-late',verified,clock=lambda:now[0],gui=True)
        self.assertEqual(caught.exception.fault.code,'RUNNER_TIMED_OUT')
        self.assertEqual(json.loads((self.root/'gui-late/result.json').read_text())['status'],'failed')

    def test_gui_cancellation_cannot_publish_success(self):
        from unittest.mock import patch
        flag=[False]
        def cancelled_gui(*a,**k):flag[0]=True;return {'completed':True}
        with patch('schemaxis.adaptors.freecad.assembly_sources_gui.inspect_verified',cancelled_gui), self.assertRaises(SchemaxisError) as caught:
            self.execute(self.root/'gui-cancel',lambda *a,**k:{'verified':True,'nativeSha256':'a'*64},cancelled=lambda:flag[0],gui=True)
        self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')
        self.assertEqual(json.loads((self.root/'gui-cancel/result.json').read_text())['status'],'failed')

    def test_concurrent_publication_change_after_verified_digest_never_launches_gui(self):
        from unittest.mock import patch
        target=self.root/'gui-changed'
        def verified_then_changed(directory,*a,**k):
            native=Path(directory)/'model.FCStd';native.write_bytes((self.root/'plate/model.FCStd').read_bytes())
            checked=hashlib.sha256(native.read_bytes()).hexdigest()
            native.write_bytes(native.read_bytes()+b'concurrent unverified save')
            return {'verified':True,'nativeSha256':checked}
        with patch('schemaxis.adaptors.freecad.gui_process.run') as launch, self.assertRaises(SchemaxisError) as caught:
            self.execute(target,verified_then_changed,gui=True)
        self.assertEqual(caught.exception.fault.code,'INPUT_CHANGED');launch.assert_not_called()
        self.assertFalse((target/'source-gui-request.json').exists())
        self.assertEqual(json.loads((target/'result.json').read_text())['status'],'failed')

    def test_overrun_during_final_verification_is_not_published_as_success(self):
        now = [0.0]

        def slow_verify(*args, **kwargs):
            now[0] += 61.0
            return {'verified': True}
        with self.assertRaises(SchemaxisError) as caught:
            self.execute(self.root/'late', slow_verify, clock=lambda: now[0])
        self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')
        self.assertEqual(json.loads((self.root/'late'/'result.json').read_text())['status'], 'failed')

    def test_cancellation_during_final_verification_is_not_published_as_success(self):
        flag = [False]

        def cancelling_verify(*args, **kwargs):
            flag[0] = True
            return {'verified': True}
        with self.assertRaises(SchemaxisError) as caught:
            self.execute(self.root/'cancel', cancelling_verify, cancelled=lambda: flag[0])
        self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
        self.assertEqual(json.loads((self.root/'cancel'/'result.json').read_text())['status'], 'failed')


class GuiStateProxyTests(unittest.TestCase):
    def test_empty_native_camera_and_legacy_visibility_record(self):
        from xml.etree import ElementTree as ET
        from schemaxis.adaptors.freecad import source_envelope
        visibility={'N0':True}
        root=ET.fromstring(gui_state.serialize(visibility))
        self.assertEqual(root[-1].tag,'Camera')
        self.assertEqual(root[-1].attrib,{'settings':''})
        current=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        root.remove(root[-1]);legacy=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'x.FCStd'
            def check(data):
                with zipfile.ZipFile(path,'w') as archive:
                    archive.writestr('GuiDocument.xml',data)
                gui_state.verify(path,visibility)
                source_envelope.gui_record(data,visibility,'source','UNSUPPORTED_SOURCE')
            check(current);check(legacy)
            for camera in ('<Camera/>','<Camera settings="authored"/>','<Camera settings=""><Foreign/></Camera>',
                           '<Camera settings="" extra="x"/>','<Camera settings=""/><Camera settings=""/>'):
                with self.subTest(camera=camera):
                    changed=legacy.replace(b'</Document>',camera.encode()+b'</Document>')
                    with self.assertRaises(ValueError):check(changed)
                    with self.assertRaises(SchemaxisError):
                        source_envelope.gui_record(changed,visibility,'source','UNSUPPORTED_SOURCE')

    def test_controlled_proxies_round_trip_and_refuse_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'x.FCStd'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Document.xml', '<Document/>')
            visibility = {'Assembly': True, 'Ground': True, 'Joint0': False, 'N0': False}
            proxies = {'Ground': 'ViewProviderGroundedJoint', 'Joint0': 'ViewProviderJoint'}
            gui_state.persist(path, visibility, proxies)
            gui_state.verify(path, visibility, proxies)
            for changed in ({'Ground': 'ViewProviderGroundedJoint'}, {**proxies, 'Joint0': 'ViewProviderGroundedJoint'}, {}):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    gui_state.verify(path, visibility, changed)
            with self.assertRaises(ValueError):
                gui_state.serialize(visibility, {'N0': 'Evil'})


class SavedIsomorphismTests(unittest.TestCase):
    """Synthetic Document.xml pairs: renamed sources must not reach another owner."""

    def document(self, path, objects):
        rows = ''.join('<Object type="%s" name="%s" id="%d"/>' % (t, n, i) for i, (n, t, _) in enumerate(objects,1))
        data = ''.join('<Object name="%s"><Properties Count="%d" TransientCount="0">%s</Properties></Object>' % (n, len(p), ''.join(p))
                       for n, _, p in objects)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Document.xml', '<Document SchemaVersion="4"><Objects Count="%d">%s</Objects><ObjectData Count="%d">%s</ObjectData></Document>'
                             % (len(objects), rows, len(objects), data))
        from schemaxis.adaptors.freecad.assembly_sources_saved import Saved
        return Saved(path)

    def test_rename_isomorphism_rejects_cross_owner_references(self):
        from schemaxis.adaptors.freecad.assembly_sources_saved import isomorphic
        label = '<Property name="Label" type="App::PropertyString"><String value="x"/></Property>'
        def sketch(varset):
            return [label, '<Property name="ExpressionEngine" type="App::PropertyExpressionEngine"><ExpressionEngine count="1">'
                    '<Expression path=".Constraints.width" expression="1 * %s.dim_width + 0 mm"/></ExpressionEngine></Property>' % varset]
        def pad(profile):
            return [label, '<Property name="Profile" type="App::PropertyLinkSub"><LinkSub value="%s" count="0"/></Property>' % profile]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            producer = self.document(tmp/'p.FCStd', [('SchemaxisParameters', 'App::VarSet', [label]),
                                                     ('N1', 'Sketcher::SketchObject', sketch('SchemaxisParameters')),
                                                     ('N2', 'PartDesign::Pad', pad('N1'))])
            mapping = {'SchemaxisParameters': 'SchemaxisParameters001', 'N1': 'N002', 'N2': 'N003'}
            def assembled(varset, profile):
                return self.document(tmp/'a.FCStd', [('SchemaxisParameters', 'App::VarSet', [label]),
                    ('N1', 'Sketcher::SketchObject', sketch('SchemaxisParameters')),
                    ('SchemaxisParameters001', 'App::VarSet', [label]),
                    ('N002', 'Sketcher::SketchObject', sketch(varset)), ('N003', 'PartDesign::Pad', pad(profile))])
            good = assembled('SchemaxisParameters001', 'N002')
            foreign = set(good.xml.types)-set(mapping.values())
            self.assertTrue(isomorphic(producer, good, mapping, foreign, [], 'B'))
            for varset, profile in (('SchemaxisParameters', 'N002'), ('SchemaxisParameters001', 'N1')):
                bad = assembled(varset, profile)
                with self.subTest(varset=varset, profile=profile), self.assertRaises(ValueError):
                    isomorphic(producer, bad, mapping, set(bad.xml.types)-set(mapping.values()), [], 'B')


if __name__ == '__main__':
    unittest.main()
