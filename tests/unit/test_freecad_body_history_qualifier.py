"""Public Body-history reproducer: real planning, independent formulae and rollback."""
import ast
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.adaptors.freecad.source_bridge import record,selected_body
from schemaxis.artifacts import atomic_json

ROOT=Path(__file__).resolve().parents[2]
TOOLS=ROOT/'tools'
sys.path.insert(0,str(TOOLS))
try:
    import freecad_body_history_cases as cases
    import freecad_body_history_guards as guards
    import qualify_freecad_body_history as qualifier
finally:sys.path.pop(0)


class BodyHistoryQualifier(unittest.TestCase):
    def test_all_six_public_recipes_compile_and_capture_finite_body_contracts(self):
        docs=cases.documents(ROOT/'examples/schemaxis',ROOT/'examples/schemaxis/freecad-body-stock.stl')
        self.assertEqual(set(docs),set(cases.expectations()))
        generations={}
        for name,doc in docs.items():
            with self.subTest(name=name):
                native=_native_plan(doc);selected_body(native)
                facts=record(doc,native)
                self.assertEqual(facts['sourceFrame'],'bodyLocal')
                self.assertEqual(set(facts)-{'sourceFrame'},{'seedHistory'} if name=='imported' else {'bodyHistory'})
                generations[name]=native['partDesign'].get('generation',1)
        self.assertEqual(generations['parametered'],1)
        self.assertTrue(all(generations[name]==2 for name in docs if name!='parametered'))

    def test_literal_enclosure_oracle_matches_independent_disjoint_mass_sum(self):
        # Base + four side walls + four annular bosses, less four floor bores.
        # Off-centre bore changes are caught by the separate plate oracle.
        h,b,r=22,5,1
        pieces=[(40*30*3,1.5),(384*(h-3),(h+3)/2),
                (4*math.pi*(4-r*r)*b,3+b/2),(-4*math.pi*r*r*3,1.5)]
        volume=sum(v for v,z in pieces);moment=sum(v*z for v,z in pieces)
        expected=cases.enclosure_oracle(h,b,r)
        self.assertAlmostEqual(expected['volume'],volume)
        self.assertAlmostEqual(expected['centreOfMass'][2],moment/volume)
        changed=cases.enclosure_oracle(h,b,1.25)
        self.assertLess(changed['volume'],volume)
        with self.assertRaises(AssertionError):qualifier.check_shape(changed,expected)
        plate=cases.plate_oracle();self.assertLess(plate['centreOfMass'][0],0)
        shifted=copy.deepcopy(plate);shifted['centreOfMass'][0]*=-1
        with self.assertRaises(AssertionError):qualifier.check_shape(shifted,plate)

    def test_noncommuting_seed_layout_and_component_oracles(self):
        local=cases.stock_point([10,6,2.5])
        # Primitive Body basis maps (x,y,z)->(z,-y,x), origin (7,8,9).
        body_world=[7+local[2],8-local[1],9+local[0]]
        component_world=cases.world_centres()['imported']
        self.assertGreater(math.dist(body_world,component_world),10)
        self.assertEqual(len(cases.stock_bounds()),6)
        self.assertEqual(cases.world_expectations()['primitive']['bounds'],[12,20,-8,4,12,32])
        world=cases.world_expectations()['imported']
        wrong=copy.deepcopy(world);wrong['centreOfMass']=local
        with self.assertRaises(AssertionError):qualifier.check_shape(wrong,world)
        centres=cases.world_centres()
        self.assertAlmostEqual(centres['parameteredAgain'][2],24.5)
        self.assertEqual(len(centres),7)

    def test_guard_failure_restores_every_owned_publication_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target=root/'packet';target.mkdir();(target/'sources').mkdir()
            atomic_json(target/'plan.json',{'parts':[{'id':'parametered','source':{}}]})
            atomic_json(target/'authored.json',{})
            atomic_json(target/'sources.json',{})
            (target/'sentinel').write_bytes(b'keep exact bytes')
            source=target/'sources/source0.FCStd'
            with ZipFile(source,'w') as archive:archive.writestr('Document.xml','<Document/>')
            originals={p:p.read_bytes() for p in target.rglob('*') if p.is_file()}
            def fail_after_write(_):
                (target/'sentinel').write_bytes(b'changed')
                raise RuntimeError('synthetic interrupted positive control')
            with patch.object(guards.registry,'verify',side_effect=fail_after_write):
                with self.assertRaisesRegex(RuntimeError,'interrupted'):
                    guards.qualify_guards(target,root/'guards',{})
            self.assertTrue(all(path.read_bytes()==data for path,data in originals.items()))
            self.assertFalse(json.loads((root/'guards/report.json').read_text())['verified'])

    def test_runner_timeout_is_not_counted_as_a_successful_guard_attack(self):
        from schemaxis.core.faults import SchemaxisError,Fault
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target=root/'packet';target.mkdir();(target/'sources').mkdir()
            atomic_json(target/'plan.json',{'parts':[{'id':'parametered','source':{}}]})
            atomic_json(target/'authored.json',{})
            atomic_json(target/'sources.json',{'parametered':{}})
            source=target/'sources/source0.FCStd'
            with ZipFile(source,'w') as archive:
                archive.writestr('Document.xml','<Document/>');archive.writestr('N1.Shape.brp','1.000')
            original=source.read_bytes();calls=[]
            def verify(_):
                calls.append(True)
                if len(calls)==1:
                    (root/'guards/native-opens.jsonl').write_text(json.dumps({'path':str(source),'pid':1})+'\n')
                    return {'verified':True}
                raise SchemaxisError(Fault('RUNNER_TIMED_OUT','synthetic timeout','worker','verification'))
            with patch.object(guards.registry,'verify',side_effect=verify),patch.object(guards,'finalise'):
                with self.assertRaises(AssertionError):guards.qualify_guards(target,root/'guards',{})
            self.assertEqual(source.read_bytes(),original)
            self.assertFalse(json.loads((root/'guards/report.json').read_text())['verified'])

    def test_documented_example_obeys_existing_sourced_assembly_structure(self):
        text=(ROOT/'docs/freecad-body-history.md').read_text()
        example=json.loads(text.split('```json\n',1)[1].split('\n```',1)[0])
        self.assertGreaterEqual(len(example['components']),2)
        self.assertEqual(len(example['joints']),len(example['components'])-1)
        # Check the actual current schema rather than only counting fixtures.
        from schemaxis.adaptors.freecad.assembly import schema
        from jsonschema import validate
        example['parts'][0]['source']='published/model.FCStd'
        validate(example,schema())

    def test_first_native_submission_failure_leaves_false_source_bound_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'proof'
            with patch.object(qualifier,'runtime_archive',return_value=b'test runtime bytes'), \
                    patch.object(qualifier.registry,'run',side_effect=RuntimeError('submission failed')):
                with self.assertRaisesRegex(RuntimeError,'submission failed'):
                    qualifier.qualify(output,sys.executable)
            report=json.loads((output/'report.json').read_text())
            self.assertFalse(report['verified'])
            self.assertEqual(report['failure']['phase'],'build-parametered')
            self.assertEqual(report['checks'],{})
            self.assertTrue(report['sourceDigest'].startswith('sha256:'))
            self.assertEqual(report['sourceStates']['constructionSourceDigest'],report['sourceDigest'])

    def test_tools_parse_without_native_application_imports(self):
        for name in ('qualify_freecad_body_history.py','freecad_body_history_cases.py','freecad_body_history_guards.py'):
            module=ast.parse((TOOLS/name).read_text())
            imports=[n for n in ast.walk(module) if isinstance(n,(ast.Import,ast.ImportFrom))]
            self.assertFalse(any(getattr(n,'module','') in ('FreeCAD','Part','FreeCADGui') for n in imports))
        for count in (-1,9,True):
            with self.assertRaises(ValueError):qualifier.qualify('unused',sys.executable,save_count=count)


if __name__=='__main__':unittest.main()
