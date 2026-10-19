"""Host tests for checked STEP import, retained-source verification and hardened export checks.

Fixtures are written by the qualifier's independent STEP writer (no CAD kernel). No
native application is started; the native qualifier is tools/qualify_freecad_step_import.py.
"""
import hashlib
import importlib.util
import json
import math
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from schemaxis.adaptors.freecad import step_source, export_checks, saved_checks
from schemaxis.adaptors.freecad.adaptor import plan, DECLARATIONS, schema
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('qualify_step', ROOT/'tools/qualify_freecad_step_import.py')
Q = importlib.util.module_from_spec(spec); spec.loader.exec_module(Q)
BASE = Q.prism(Q.OUTER, [Q.HOLE], 0, 10)
TRUTH = Q.facts(BASE)


def text(path):
    return Path(path).read_bytes()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, faces=BASE, **options):
        return Q.write_planar(self.root/name, faces, name='bracket', **options)

    def code(self, call):
        with self.assertRaises(SchemaxisError) as caught:
            call()
        return caught.exception.fault

    def doc(self, path, **options):
        return Q.importing(path, Q.base_expect(TRUTH), **options)


class ScannerTests(Fixture):
    def test_supported_units_relationship_and_voids_are_admitted(self):
        cases = {'mm': BASE, 'cm': Q.transform(BASE, Q.I3, 0.1), 'm': Q.transform(BASE, Q.I3, 0.001), 'inch': Q.transform(BASE, Q.I3, 1/25.4)}
        for unit, faces in cases.items():
            facts = step_source.scan(text(self.write(unit+'.step', faces, unit=unit)))
            self.assertEqual((facts['unit'], facts['schema'], facts['structure'], facts['solid']), (unit, 'AP214', 'direct', 'MANIFOLD_SOLID_BREP'))
        self.assertEqual(step_source.scan(text(self.write('rel.step', structure='relationship')))['structure'], 'relationship')
        void = Q.prism([(-7, -5), (7, -5), (7, 5), (-7, 5)], [], 1, 9)
        self.assertEqual(step_source.scan(text(self.write('void.step', Q.prism([(-20, -15), (20, -15), (20, 15), (-20, 15)], [], 0, 10),
                                                          voids=[void])))['solid'], 'BREP_WITH_VOIDS')
        cylinder = step_source.scan(text(Q.write_cylinder(self.root/'cyl.step')))
        self.assertEqual(cylinder['unit'], 'mm')

    def refuse(self, data, code):
        with self.assertRaises(step_source._Refuse) as caught:
            step_source.scan(data)
        self.assertEqual(caught.exception.code, code, caught.exception.args)
        return caught.exception

    def test_closed_structure_and_lexical_traps(self):
        data = text(self.write('base.step')).decode()
        head, body = data.split('DATA;\n', 1)
        # Strings and comments mentioning units, assemblies and B-reps are inert.
        trap = head.replace("('Schemaxis qualification part')", "('SI_UNIT($,.METRE.); #9=MAPPED_ITEM'')')") + 'DATA;\n' \
            + "/* #99=MANIFOLD_SOLID_BREP('x',#1); NEXT_ASSEMBLY_USAGE_OCCURRENCE */\n" + body
        self.assertEqual(step_source.scan(trap.encode())['unit'], 'mm')
        orphan = ("#90001=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );\n"
                  "#90002=( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT((#90001)) REPRESENTATION_CONTEXT('','') );\n")
        self.refuse((head+'DATA;\n'+orphan+body).encode(), 'UNSUPPORTED_SOURCE')
        self.refuse(data.replace('GLOBAL_UNIT_ASSIGNED_CONTEXT((#9,#10,#11))', 'GLOBAL_UNIT_ASSIGNED_CONTEXT((#10,#11))').encode(), 'UNDECLARED_UNIT')
        self.refuse(data.replace('GLOBAL_UNIT_ASSIGNED_CONTEXT((#9,#10,#11))', 'GLOBAL_UNIT_ASSIGNED_CONTEXT((#9,#9,#10,#11))').encode(), 'UNDECLARED_UNIT')
        for entity in ("NEXT_ASSEMBLY_USAGE_OCCURRENCE('','','',#7,#7,$)", "MAPPED_ITEM('',#17,#17)", "ITEM_DEFINED_TRANSFORMATION('','',#17,#17)",
                       "EXTERNALLY_DEFINED_ITEM(#1,#1)", "DRAUGHTING_PRE_DEFINED_COLOUR('red')"):
            self.refuse((head+'DATA;\n#95000='+entity+';\n'+body).encode(), 'UNSUPPORTED_SOURCE')
        self.refuse((head+'DATA;\n#1=CARTESIAN_POINT(\'\',(0.,0.,0.));\n'+body).encode(), 'UNSUPPORTED_SOURCE')   # duplicate id
        self.refuse(data.replace('#13=', '#13=', 1).replace(',#13)', ',#99999)', 1).encode(), 'UNSUPPORTED_SOURCE')  # unresolved
        self.refuse(data.encode()+b'DATA;\nENDSEC;\n', 'UNSUPPORTED_SOURCE')
        self.refuse(data.replace('bracket', 'bräcket', 1).encode(), 'UNSUPPORTED_SOURCE')
        self.refuse(b'\x1f\x8b' + data.encode(), 'UNSUPPORTED_SOURCE')
        self.refuse(data.replace('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }', 'IFC4').encode(), 'UNSUPPORTED_SOURCE')
        self.refuse(data.replace('/*', '').replace("DATA;\n", "DATA;\n/* unterminated\n", 1).encode(), 'UNSUPPORTED_SOURCE')
        foot = data.replace("#9=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );",
                            "#9=( CONVERSION_BASED_UNIT('FOOT',#90009) LENGTH_UNIT() NAMED_UNIT(#90010) );\n"
                            "#90008=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );\n"
                            "#90009=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(304.8),#90008);\n#90010=DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.);")
        self.refuse(foot.encode(), 'UNSUPPORTED_UNITS')

    def test_resource_bounds(self):
        data = text(self.write('base.step'))
        with mock.patch.object(step_source, 'MAX_LOOP_EDGES', 7):
            self.refuse(data, 'RESOURCE_LIMIT')
        with mock.patch.object(step_source, 'MAX_ENTITIES', 100):
            self.refuse(data, 'RESOURCE_LIMIT')
        with mock.patch.object(step_source, 'MAX_BYTES', 1000):
            self.refuse(data, 'RESOURCE_LIMIT')
        head, body = data.decode().split('DATA;\n', 1)
        nested = '#95000=CARTESIAN_POINT(\'\','+'('*20+'0.'+')'*20+');\n'
        self.refuse((head+'DATA;\n'+nested+body).encode(), 'RESOURCE_LIMIT')
        long_string = "#95000=PRODUCT_CATEGORY('"+'x'*(step_source.MAX_STRING+1)+"','');\n"
        self.refuse((head+'DATA;\n'+long_string+body).encode(), 'RESOURCE_LIMIT')
        self.assertEqual((step_source.MAX_BYTES, step_source.MAX_ENTITIES, step_source.MAX_LOOP_EDGES), (32*1024*1024, 100000, 2000))

    def test_linked_representations_must_agree_on_units(self):
        data = text(self.write('rel.step', structure='relationship')).decode()
        conflict = data.replace("SHAPE_REPRESENTATION('bracket',(#", "SHAPE_REPRESENTATION('bracket',(#", 1)
        lines = conflict.split('\n')
        index = next(i for i, l in enumerate(lines) if "SHAPE_REPRESENTATION('bracket'" in l)
        context = "#95001=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT($,.METRE.) );\n#95002=( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT((#95001)) REPRESENTATION_CONTEXT('','') )"
        lines[index] = lines[index].rsplit(',', 1)[0] + ',#95002);'
        lines.insert(index, context+';')
        self.refuse('\n'.join(lines).encode(), 'UNDECLARED_UNIT')


class PlanTests(Fixture):
    def test_plan_binds_source_facts_frames_and_is_read_only(self):
        path = self.write('bracket.step')
        before = sorted(self.root.iterdir())
        node = plan(self.doc(path, orientation={'z': '+Y', 'x': '+X'}, placement={'position': [1, 2, 3], 'clocking': 90}))['nodes'][0]
        self.assertEqual(sorted(self.root.iterdir()), before)
        self.assertEqual(node['source']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(node['source']['path'], str(path))
        self.assertEqual(node['frame']['partFromFile'], [[1, 0, 0], [0, 0, -1], [0, 1, 0]])
        self.assertEqual(node['frame']['worldFromPart'], [[0, -1, 0], [1, 0, 0], [0, 0, 1]])
        self.assertEqual(node['options']['orientation'], {'z': '+Y', 'x': '+X'})
        path.write_text(path.read_text().replace("'2026-10-19T00:00:00'", "'2026-10-19T00:00:01'"))
        self.assertNotEqual(plan(self.doc(path))['nodes'][0]['source']['sha256'], node['source']['sha256'])

    def test_located_semantic_faults(self):
        path = self.write('bracket.step')
        inch = self.write('inch.step', unit='inch')
        cases = [
            (Q.importing(inch, Q.base_expect(TRUTH)), 'UNIT_MISMATCH', 'part.options.units'),
            (Q.importing(path, {'volume': {'value': 1}}), 'INVALID_ARGUMENT', 'part.options.expect'),
            (Q.importing(path, {'volume': {'value': 1}, 'points': {'inside': [[0, 0, 5]], 'guard': 0.1}}), 'INVALID_ARGUMENT', 'part.options.expect'),
            (Q.importing(path, {'volume': {'value': 1}, 'points': {'guard': 0.1}}), 'INVALID_ARGUMENT', 'part.options.expect.points'),
            (Q.importing(path, Q.base_expect(TRUTH), orientation={'z': '+Y'}), 'INVALID_AXIS', 'part.options.orientation.x'),
            (Q.importing(path, Q.base_expect(TRUTH), orientation={'z': '+Y', 'x': '-Y'}), 'INVALID_AXIS', 'part.options.orientation.x'),
            (Q.importing(path, {**Q.base_expect(TRUTH), 'bounds': {'value': [1, 0, 0, 1, 0, 1]}}), 'INVALID_ARGUMENT', 'part.options.expect.bounds'),
            (Q.importing(self.root/'absent.step', Q.base_expect(TRUTH)), 'RESOURCE_NOT_FOUND', 'part.options.file'),
        ]
        for document, code, location in cases:
            with self.subTest(code=code, location=location):
                fault = self.code(lambda: plan(document))
                self.assertEqual((fault.code, fault.location), (code, location))
        missing = Q.importing(path, Q.base_expect(TRUTH)); del missing['nodes'][0]['options']['expect']
        self.assertEqual(self.code(lambda: plan(missing)).code, 'MISSING_ARGUMENT')
        units = Q.importing(path, Q.base_expect(TRUTH), units='foot')
        self.assertEqual(self.code(lambda: plan(units)).code, 'INVALID_ARGUMENT')
        guard = Q.importing(path, {'volume': {'value': 1}, 'points': {'inside': [[0, 0, 5]], 'outside': [[0, 0, 11]], 'guard': 0}})
        self.assertEqual(self.code(lambda: plan(guard)).code, 'INVALID_ARGUMENT')
        link = self.root/'link.step'; link.symlink_to(path)
        self.assertEqual(self.code(lambda: plan(self.doc(link))).code, 'UNSUPPORTED_SOURCE')
        body = self.doc(path); body['nodes'].insert(0, {'id': 'body', 'filter': 'body'})
        self.assertEqual(self.code(lambda: plan(body)).code, 'UNSUPPORTED_SOURCE')
        from schemaxis.adaptors.freecad.live import prepare as prepare_live
        self.assertEqual(self.code(lambda: prepare_live(self.doc(path))).code, 'UNSUPPORTED_LIVE_INPUT')

    def test_old_routes_and_schema_order_are_unchanged(self):
        self.assertEqual(list(DECLARATIONS)[-1], 'importSTEP')
        alternatives = schema()['properties']['nodes']['items']['oneOf']
        self.assertEqual(alternatives[-1]['properties']['filter'], {'const': 'importSTEP'})
        legacy = plan({'version': 'schemaxis.freecad/1', 'nodes': [{'id': 's', 'filter': 'readSTEP', 'options': {'file': 'x.step'}}], 'output': 's'})
        self.assertEqual(set(legacy['nodes'][0]), {'id', 'filter', 'options', 'inputs'})


class SourceLifecycleTests(Fixture):
    def captured_run(self, relative=False):
        source = self.write('supplier.step')
        run = self.root/'run'; run.mkdir()
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            document = self.doc(Path('supplier.step') if relative else source)
            prepared = plan(document)
        finally:
            os.chdir(cwd)
        from schemaxis.adaptors.freecad.adaptor import capture
        records = capture(prepared, run)
        for name, value in (('authored.json', document), ('plan.json', prepared), ('sources.json', records)):
            (run/name).write_text(json.dumps(value))
        return source, run, document, prepared

    def test_retained_inputs_survive_original_removal_and_cwd_change(self):
        from schemaxis.adaptors.freecad.integration import retainedInputs, reusableInputs
        for relative in (False, True):
            with self.subTest(relative=relative):
                source, run, document, prepared = self.captured_run(relative)
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                self.assertEqual(retainedInputs(run, document), {str(source): digest})
                source.unlink()
                elsewhere = tempfile.mkdtemp()
                cwd = os.getcwd()
                try:
                    os.chdir(elsewhere)
                    self.assertEqual(retainedInputs(run, document), {str(source): digest})
                    self.assertEqual(self.code(lambda: reusableInputs(document)).code, 'RESOURCE_NOT_FOUND')
                finally:
                    os.chdir(cwd); os.rmdir(elsewhere)
                for path in run.iterdir(): path.unlink()
                run.rmdir()

    def test_current_source_change_invalidates_reuse_but_not_retained_provenance(self):
        from schemaxis.adaptors.freecad.integration import retainedInputs, reusableInputs
        source, run, document, _ = self.captured_run()
        captured = retainedInputs(run, document)
        self.assertEqual(reusableInputs(document), captured)
        source.write_text(source.read_text().replace("'2026-10-19T00:00:00'", "'2026-10-19T09:00:00'"))
        self.assertNotEqual(reusableInputs(document), captured)
        self.assertEqual(retainedInputs(run, document), captured)
        # The shared scheduler compares this map with recorded job hashes; a forged record no longer matches.
        from schemaxis.parallel import retained_inputs
        self.assertEqual(retained_inputs(run, document), captured)
        self.assertNotEqual({k: '0'*64 for k in captured}, captured)

    def test_retained_copy_tampering_and_forged_records_are_refused(self):
        from schemaxis.adaptors.freecad.integration import retainedInputs
        source, run, document, _ = self.captured_run()
        retained = run/'import-0.step'
        retained.write_text(retained.read_text().replace('bracket', 'brackeT', 1))
        self.assertEqual(self.code(lambda: retainedInputs(run, document)).code, 'VERIFICATION_FAILED')
        records = json.loads((run/'sources.json').read_text())
        records['part']['sha256'] = hashlib.sha256(retained.read_bytes()).hexdigest()   # refreshed record
        (run/'sources.json').write_text(json.dumps(records))
        self.assertEqual(self.code(lambda: retainedInputs(run, document)).code, 'VERIFICATION_FAILED')   # replayed plan differs
        records['part']['file'] = str(self.root/'elsewhere/supplier.step')
        (run/'sources.json').write_text(json.dumps(records))
        self.assertEqual(self.code(lambda: retainedInputs(run, document)).code, 'VERIFICATION_FAILED')
        self.assertIsNone(retainedInputs(run, {**document, 'designStudy': {}}))

    def test_capture_requires_planned_bytes(self):
        from schemaxis.adaptors.freecad.adaptor import capture
        source = self.write('supplier.step')
        prepared = plan(self.doc(source))
        source.write_text(source.read_text().replace("'2026-10-19T00:00:00'", "'2026-10-19T00:00:02'"))
        run = self.root/'run'; run.mkdir()
        self.assertEqual(self.code(lambda: capture(prepared, run)).code, 'INPUT_CHANGED')

    def test_capture_failure_and_cancellation_leave_failed_results_without_native_launch(self):
        from schemaxis.adaptors.freecad import adaptor
        source = self.write('supplier.step')
        executable = self.root/'freecadcmd'; executable.write_text('#!/bin/sh\nexit 0\n'); executable.chmod(0o755)
        with mock.patch.object(adaptor, 'SubprocessRunner') as runner, mock.patch.object(adaptor, 'cancellation_requested', return_value=True):
            fault = self.code(lambda: adaptor._native_run(self.doc(source), self.root/'cancelled', executable=str(executable)))
            self.assertEqual(fault.code, 'RUNNER_CANCELLED')
            runner.return_value.assert_not_called()
        self.assertEqual(json.loads((self.root/'cancelled/result.json').read_text())['status'], 'failed')
        with mock.patch.object(adaptor, 'capture', side_effect=SchemaxisError(__import__('schemaxis.core.faults', fromlist=['Fault']).Fault(
                'INPUT_CHANGED', 'changed', 'part.options.file', 'pipeline'))), mock.patch.object(adaptor, 'SubprocessRunner') as runner:
            self.assertEqual(self.code(lambda: adaptor._native_run(self.doc(source), self.root/'capture', executable=str(executable))).code, 'INPUT_CHANGED')
            runner.assert_not_called()
        self.assertEqual(json.loads((self.root/'capture/result.json').read_text())['status'], 'failed')


def box_triangles(lo, hi, origin=(0, 0, 0)):
    (x0, y0, z0), (x1, y1, z1) = [[a+b for a, b in zip(p, origin)] for p in (lo, hi)]
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return [(v[a], v[b], v[c]) for q in quads for a, b, c in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))]


def write_stl(path, triangles):
    with open(path, 'wb') as f:
        f.write(b' '*80); f.write(struct.pack('<I', len(triangles)))
        for a, b, c in triangles:
            f.write(struct.pack('<12fH', 0, 0, 0, *a, *b, *c, 0))
    return path


def native(lo, hi, origin=(0, 0, 0), curved=0.0):
    lo = [a+b for a, b in zip(lo, origin)]; hi = [a+b for a, b in zip(hi, origin)]
    size = [h-l for l, h in zip(lo, hi)]
    return {'valid': True, 'solids': 1, 'volume': size[0]*size[1]*size[2], 'area': 2*(size[0]*size[1]+size[1]*size[2]+size[0]*size[2]),
            'curvedArea': curved, 'faces': 6, 'bounds': [lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]],
            'centreOfMass': [(l+h)/2 for l, h in zip(lo, hi)]}


class ExportCheckTests(Fixture):
    def test_exact_planar_mesh_and_far_placement_are_accepted(self):
        for origin in ((0, 0, 0), (99950, -99950, 99950)):
            path = write_stl(self.root/'box.stl', box_triangles((0, 0, 0), (40, 30, 10), origin))
            record = export_checks.check_stl(path, native((0, 0, 0), (40, 30, 10), origin), 0.05)
            self.assertLessEqual(abs(record['volumeError']), record['volumeAllowance'])
            self.assertGreater(record['volumeAllowance'], 0)

    def test_inverted_dropped_and_shifted_meshes_are_refused(self):
        tri = box_triangles((0, 0, 0), (40, 30, 10))
        facts = native((0, 0, 0), (40, 30, 10))
        cases = {'inverted': [(a, c, b) for a, b, c in tri], 'dropped': tri[:-1],
                 'shifted': [tuple((p[0]+1.0, p[1], p[2]) for p in t) for t in tri],
                 'scaled': [tuple(tuple(1.01*c for c in p) for p in t) for t in tri]}
        for label, triangles in cases.items():
            with self.subTest(label=label):
                fault = self.code(lambda: export_checks.check_stl(write_stl(self.root/(label+'.stl'), triangles), facts, 0.05))
                self.assertEqual(fault.code, 'VERIFICATION_FAILED')

    def test_mirrored_asymmetric_mesh_is_refused_by_its_centre(self):
        # A box whose declared native centre is off the bounds centre (as for an asymmetric part).
        tri = box_triangles((0, 0, 0), (40, 30, 10))
        facts = native((0, 0, 0), (40, 30, 10)); facts['centreOfMass'] = [19.0, 15, 5]
        fault = self.code(lambda: export_checks.check_stl(write_stl(self.root/'m.stl', tri), facts, 0.05))
        self.assertIn('centre', fault.message)

    def test_budgets_fail_closed_with_advice(self):
        tri = box_triangles((0, 0, 0), (40, 30, 10))
        facts = native((0, 0, 0), (40, 30, 10), curved=2400.0)
        fault = self.code(lambda: export_checks.check_stl(write_stl(self.root/'u.stl', tri), facts, 10.0))
        self.assertIn('uninformative', fault.message)
        coarse = [tuple(tuple(1.003*c for c in p) for p in t) for t in tri]   # within the deflection budget, beyond 0.5 %
        facts = native((0, 0, 0), (40, 30, 10), curved=2400.0)
        fault = self.code(lambda: export_checks.check_stl(write_stl(self.root/'c.stl', coarse), facts, 0.5))
        self.assertIn('linearDeflection', fault.recovery or dict(fault.observed).get('recovery', ''))
        for broken in ({'curvedArea': 1e9}, {'volume': float('nan')}, {'centreOfMass': [500, 0, 0]}, {'solids': 2}, {'faces': 0}):
            bad = {**native((0, 0, 0), (40, 30, 10)), **broken}
            with self.subTest(broken=broken):
                self.assertEqual(self.code(lambda: export_checks.check_stl(write_stl(self.root/'b.stl', tri), bad, 0.05)).code, 'VERIFICATION_FAILED')


class NoDowngradeTests(unittest.TestCase):
    def test_missing_or_old_hardened_evidence_requires_a_rerun(self):
        good = {'exportEvidence': {'version': saved_checks.EXPORT_EVIDENCE}}
        saved_checks.require_hardened(good, good, '/run')
        for built, receipt in (({}, good), (good, {}), ({'exportEvidence': {'version': 'schemaxis.freecad.export/1'}}, good),
                               (good, {'exportEvidence': None})):
            with self.assertRaises(SchemaxisError) as caught:
                saved_checks.require_hardened(built, receipt, '/run')
            self.assertEqual(caught.exception.fault.code, 'RERUN_REQUIRED')
        native = (ROOT/'src/schemaxis/adaptors/freecad/native.py').read_text()
        self.assertIn("EXPORT_EVIDENCE = '%s'" % saved_checks.EXPORT_EVIDENCE, native)

    def test_verify_has_no_authored_switch_for_hardened_checks(self):
        options = DECLARATIONS['importSTEP']['options']
        self.assertFalse({'exportChecks', 'legacy', 'skipChecks'} & set(options))
        self.assertNotIn('exportChecks', schema()['properties'])


class ArchiveBoundaryTests(Fixture):
    """A refreshed-digest corrupt or malformed FCStd gives a structured, located fault, never a bare decoder error."""

    def run_fixture(self):
        import copy
        import zipfile
        from schemaxis.adaptors.freecad.adaptor import FILES
        from schemaxis.artifacts import atomic_json
        from schemaxis.publication_metadata import finalise
        run = self.root/'run'; run.mkdir()
        doc = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'block', 'filter': 'box'}], 'output': 'block'}
        prepared = plan(doc)
        shape = native((0, 0, 0), (10, 10, 10))
        evidence = {'version': saved_checks.EXPORT_EVIDENCE, 'shape': shape,
                    'meshing': {'linearDeflection': prepared['linearDeflection']/2, 'angularDeflection': 0.1, 'relative': False}}
        atomic_json(run/'authored.json', doc); atomic_json(run/'plan.json', prepared)
        atomic_json(run/'built.json', {'definition': prepared, 'shape': shape, 'importObservations': {}, 'exportEvidence': evidence})
        atomic_json(run/'result.json', {'verified': True})
        Q.write_planar(run/'model.step', Q.prism([(0, 0), (10, 0), (10, 10), (0, 10)], [], 0, 10))
        write_stl(run/'model.stl', box_triangles((0, 0, 0), (10, 10, 10)))
        with zipfile.ZipFile(run/'model.FCStd', 'w') as archive:
            archive.writestr('Document.xml', self.DOCUMENT)
        artifacts = [{'file': str(run/f), 'kind': k, 'units': 'mm', 'sha256': hashlib.sha256((run/f).read_bytes()).hexdigest()} for f, k in FILES]
        receipt = {'status': 'succeeded', 'freshProcess': True, 'units': 'mm', 'definition': prepared, 'runtime': ['1', '1', '4'],
                   'importObservations': {}, 'exportEvidence': {'version': saved_checks.EXPORT_EVIDENCE, 'native': copy.deepcopy(shape),
                                                                'step': copy.deepcopy(shape)},
                   'native': copy.deepcopy(shape), 'step': copy.deepcopy(shape),
                   'mesh': {'solid': True, 'volume': 1000., 'facets': 12, 'bounds': shape['bounds']}, 'artifacts': artifacts}
        atomic_json(run/'verification.json', receipt)
        finalise(run)
        return run

    DOCUMENT = ('<Document><Objects><Object name="N0" type="Part::Box"/></Objects>'
                '<ObjectData><Object name="N0"><Properties/></Object></ObjectData></Document>')

    def replace(self, run, data):
        """What an attacker can do: replace the archive, re-digest it and regenerate shared metadata."""
        from schemaxis.publication_metadata import finalise
        (run/'model.FCStd').write_bytes(data)
        receipt = json.loads((run/'verification.json').read_text())
        receipt['artifacts'][2]['sha256'] = hashlib.sha256(data).hexdigest()
        (run/'verification.json').write_text(json.dumps(receipt))
        finalise(run)

    def archive(self, members, method=None):
        import io
        import zipfile
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', method or zipfile.ZIP_STORED) as archive:
            for name, data in members:
                archive.writestr(name, data)
        return out.getvalue()

    def fault(self, run):
        from schemaxis.adaptors.freecad.adaptor import verify
        with self.assertRaises(SchemaxisError) as caught:
            verify(run)
        return caught.exception.fault

    def test_valid_control_and_every_corrupt_or_malformed_archive(self):
        import zipfile
        from schemaxis.adaptors.freecad.adaptor import verify
        run = self.run_fixture()
        self.assertTrue(verify(run)['verified'])
        valid = (run/'model.FCStd').read_bytes()
        deflated = bytearray(self.archive([('Document.xml', self.DOCUMENT*50)], zipfile.ZIP_DEFLATED))
        start = deflated.index(b'Document.xml') + len('Document.xml')
        for i in range(start+20, start+60):
            deflated[i] ^= 0xFF
        cases = {
            'not-a-zip': b'not a zip archive',
            'truncated': valid[:len(valid)//2],
            'malformed-xml': self.archive([('Document.xml', '<Document><Objects')]),
            'missing-document': self.archive([('GuiDocument.xml', '<Document/>')]),
            'duplicate-document': self.archive([('Document.xml', self.DOCUMENT), ('Document.xml', self.DOCUMENT)]),
            'oversized-document': self.archive([('Document.xml', ' '*(32*1024*1024+1))], zipfile.ZIP_DEFLATED),
            'corrupt-member': bytes(deflated),
            'doctype-entity': self.archive([('Document.xml', '<!DOCTYPE d [<!ENTITY e "x">]><Document/>')]),
        }
        for label, data in cases.items():
            with self.subTest(label=label):
                self.replace(run, data)
                fault = self.fault(run)
                self.assertEqual((fault.code, fault.location), ('VERIFICATION_FAILED', 'model.FCStd'), (label, fault.message))
        self.replace(run, valid)
        self.assertTrue(verify(run)['verified'])

    def test_historical_runs_still_require_a_rerun_before_archive_checks(self):
        from schemaxis.artifacts import atomic_json
        run = self.run_fixture()
        self.replace(run, b'not a zip archive')
        receipt = json.loads((run/'verification.json').read_text()); receipt.pop('exportEvidence')
        atomic_json(run/'verification.json', receipt)
        self.assertEqual(self.fault(run).code, 'RERUN_REQUIRED')

    def test_parameter_and_body_readers_map_archive_errors(self):
        from schemaxis.adaptors.freecad import parameters, part_design_saved
        from schemaxis.adaptors.freecad.adaptor import _native_plan
        bad = self.root/'bad.FCStd'
        for data in (b'not a zip archive', self.archive([('Document.xml', '<Document><Objects')])):
            bad.write_bytes(data)
            prepared = _native_plan(json.loads((ROOT/'examples/schemaxis/freecad-part-design.json').read_text()))
            for reader in (lambda: parameters.verify_saved(prepared, bad), lambda: part_design_saved.verify(prepared, bad)):
                with self.assertRaises(SchemaxisError) as caught:
                    reader()
                self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_programmer_errors_are_not_converted(self):
        from schemaxis.adaptors.freecad import document_xml
        self.assertFalse(set(document_xml.ARCHIVE_ERRORS) & {Exception, RuntimeError, TypeError, AttributeError, NameError})
        run = self.run_fixture()
        with mock.patch.object(document_xml, 'Document', side_effect=RuntimeError('programming defect')):
            with self.assertRaises(RuntimeError):
                saved_checks.verify_saved_document(run/'model.FCStd', plan(json.loads((run/'authored.json').read_text())), {})


def patch_member(data, name, *, flags=None, method=None, local_only=False):
    """Set a member's general-purpose flags or compression method in its local and central headers."""
    data = bytearray(data)
    encoded = name.encode()
    local = 0
    while True:
        local = data.index(b'PK\x03\x04', local)
        size = struct.unpack_from('<H', data, local+26)[0]
        if bytes(data[local+30:local+30+size]) == encoded:
            break
        local += 4
    central = 0
    while True:
        central = data.index(b'PK\x01\x02', central)
        size = struct.unpack_from('<H', data, central+28)[0]
        if bytes(data[central+46:central+46+size]) == encoded:
            break
        central += 4
    for offset, base in ((6, local), (8, central)) if flags is not None else ():
        if base == central and local_only:
            continue
        struct.pack_into('<H', data, base+offset, flags)
    for offset, base in ((8, local), (10, central)) if method is not None else ():
        struct.pack_into('<H', data, base+offset, method)
    return bytes(data)


class ArchiveEdgeTests(ArchiveBoundaryTests):
    """File-controlled ZIP features and XML declarations are refused before decoding, in every XML encoding."""

    ENTITY = '<!DOCTYPE Document [<!ENTITY name "N0">]>' + ArchiveBoundaryTests.DOCUMENT.replace('name="N0"', 'name="&name;"', 1)

    def located(self, run):
        fault = self.fault(run)
        self.assertEqual((fault.code, fault.location), ('VERIFICATION_FAILED', 'model.FCStd'), fault.message)
        return fault

    def test_unsupported_zip_flags_and_methods_are_refused_before_decoding(self):
        import zipfile
        from schemaxis.adaptors.freecad.adaptor import verify
        run = self.run_fixture()
        stored = self.archive([('Document.xml', self.DOCUMENT)])
        deflated = self.archive([('Document.xml', self.DOCUMENT)], zipfile.ZIP_DEFLATED)
        for control in (stored, deflated):
            self.replace(run, control)
            self.assertTrue(verify(run)['verified'])
        cases = {'encrypted': dict(flags=1), 'patched': dict(flags=1 << 5), 'strong-encryption': dict(flags=1 << 6),
                 'masked-headers': dict(flags=1 << 13), 'method-99': dict(method=99), 'method-bzip2': dict(method=12),
                 'local-only-patched': dict(flags=1 << 5, local_only=True)}
        for label, change in cases.items():
            with self.subTest(label=label):
                self.replace(run, patch_member(deflated, 'Document.xml', **change))
                self.located(run)
        self.replace(run, deflated)
        self.assertTrue(verify(run)['verified'])

    def test_dtd_and_entities_are_refused_in_every_accepted_encoding(self):
        from schemaxis.adaptors.freecad.adaptor import verify
        run = self.run_fixture()
        native = "<?xml version='1.0' encoding='utf-8'?>" + self.DOCUMENT
        self.replace(run, self.archive([('Document.xml', native.encode('utf-8'))]))
        self.assertTrue(verify(run)['verified'])                       # FreeCAD's native encoding
        self.replace(run, self.archive([('Document.xml', self.DOCUMENT.encode('utf-16'))]))
        self.assertTrue(verify(run)['verified'])                       # the policy is about DTDs, not encodings
        cases = {'entity-utf8': self.ENTITY.encode('utf-8'), 'entity-utf16': self.ENTITY.encode('utf-16'),
                 'entity-utf16-be': '\ufeff'.encode('utf-16-be') + self.ENTITY.encode('utf-16-be'),
                 'doctype-only-utf16': ('<!DOCTYPE Document>' + self.DOCUMENT).encode('utf-16'),
                 'parameter-entity-utf16': ('<!DOCTYPE Document [<!ENTITY % p "x">]>' + self.DOCUMENT).encode('utf-16'),
                 'unknown-encoding': ("<?xml version='1.0' encoding='x-schemaxis-unknown'?>" + self.DOCUMENT).encode()}
        for label, data in cases.items():
            with self.subTest(label=label):
                self.assertLess(len(data), 4096)                       # bounded, single harmless entity at most
                self.replace(run, self.archive([('Document.xml', data)]))
                self.located(run)

    def test_gui_document_reader_shares_the_member_and_xml_policy(self):
        import io
        import zipfile
        from schemaxis.adaptors.freecad import gui_state
        visibility = {'N0': True}
        valid = gui_state.serialize(visibility)
        path = self.root/'gui.FCStd'
        def write(data, method=zipfile.ZIP_DEFLATED):
            path.write_bytes(self.archive([('Document.xml', self.DOCUMENT), ('GuiDocument.xml', data)], method))
        write(valid); gui_state.verify(path, visibility)
        write(valid, zipfile.ZIP_STORED); gui_state.verify(path, visibility)
        entity = ('<!DOCTYPE Document [<!ENTITY t "true">]>' + valid.decode().split('?>', 1)[1].replace("value=\"true\"", "value=\"&t;\"", 1))
        from schemaxis.adaptors.freecad.document_xml import ARCHIVE_ERRORS
        for label, data in {'entity-utf16': entity.encode('utf-16'), 'entity-utf8': entity.encode()}.items():
            with self.subTest(label=label):
                write(data)
                with self.assertRaises(ARCHIVE_ERRORS):
                    gui_state.verify(path, visibility)
        write(valid)
        path.write_bytes(patch_member(path.read_bytes(), 'GuiDocument.xml', flags=1))
        with self.assertRaises(ARCHIVE_ERRORS):
            gui_state.verify(path, visibility)
        write(valid)
        path.write_bytes(patch_member(path.read_bytes(), 'GuiDocument.xml', method=99))
        with self.assertRaises(ARCHIVE_ERRORS):
            gui_state.verify(path, visibility)


class MemberReaderLayerTests(unittest.TestCase):
    """Each validation layer of the bounded member reader refuses its own case."""

    def archive(self, data_change=None):
        import io
        import zipfile
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('Document.xml', ArchiveBoundaryTests.DOCUMENT)
        data = out.getvalue()
        return data_change(data) if data_change else data

    def reason(self, data, read=None):
        import io
        import zipfile
        from schemaxis.adaptors.freecad import document_xml
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if read:
                archive.read = read
            with self.assertRaises(document_xml.UnsupportedArchive) as caught:
                document_xml.read_member(archive, 'Document.xml', 1 << 20)
        return str(caught.exception)

    def central_only(self, data, offset, value):
        data = bytearray(data); central = data.index(b'PK\x01\x02')
        struct.pack_into('<H', data, central+offset, value)
        return bytes(data)

    def test_layers(self):
        self.assertIn('uses encryption', self.reason(self.central_only(self.archive(), 8, 1)))
        self.assertIn('compression method', self.reason(self.central_only(self.archive(), 10, 99)))
        self.assertIn('local header', self.reason(patch_member(self.archive(), 'Document.xml', flags=1 << 5, local_only=True)))
        def library_refusal(*_):
            raise NotImplementedError('That compression method is not supported')
        self.assertIn('could not be decoded', self.reason(self.archive(), read=library_refusal))
        import io
        import zipfile
        from schemaxis.adaptors.freecad import document_xml
        with zipfile.ZipFile(io.BytesIO(self.archive())) as archive:
            self.assertEqual(document_xml.read_member(archive, 'Document.xml', 1 << 20), ArchiveBoundaryTests.DOCUMENT.encode())


if __name__ == '__main__':
    unittest.main()
