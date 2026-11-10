"""Independent prospective frame oracles and public authoring controls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
try:
    import freecad_body_frame_cases as cases
    import qualify_freecad_body_frame as qualifier
    import freecad_body_frame_guards as guards
finally:sys.path.pop(0)


class BodyFrameQualifier(unittest.TestCase):
    def test_source_open_audit_observes_private_admitted_copies(self):
        public='/owned/pure/sources/source0.FCStd'
        private='/tmp/fresh-history/sources/source0.FCStd'
        others=['/tmp/reference/model.FCStd','/owned/pure/model.FCStd',
                '/tmp/reference/source0.FCStd','/tmp/reference/sources/body.FCStd']
        self.assertEqual(guards.source_opens([public,private,*others]),[public,private])
        self.assertEqual(guards.source_opens(others),[])

    def test_public_variants_compile_and_both_body_frames_are_explicit(self):
        for file in ('freecad-placed-body.json','freecad-placed-body-attached.json','freecad-placed-bodies.json'):
            authored=json.loads((ROOT/'examples/schemaxis'/file).read_text());native=_native_plan(authored)
            self.assertNotIn('seeds',native['partDesign'])
            self.assertIn('frame',native['nodes'][0]['options'])
        invalid=json.loads((ROOT/'examples/schemaxis/freecad-placed-body-invalid.json').read_text())
        with self.assertRaises(SchemaxisError) as caught:_native_plan(invalid)
        self.assertEqual(caught.exception.fault.code,'INVALID_FRAME')

    def test_literal_profile_then_body_point_disproves_wrong_order(self):
        s=cases.apply(cases.matrix(cases.PROFILE),[1,2,3]);self.assertEqual(s,[6,5,7])
        world=cases.apply(cases.matrix(cases.BODY),s)
        for a,b in zip(world,[10.76,-6.32,21.6]):self.assertAlmostEqual(a,b)
        wrong=cases.apply(cases.matrix(cases.PROFILE),cases.apply(cases.matrix(cases.BODY),[1,2,3]))
        with self.assertRaises(AssertionError):qualifier.near(world,wrong)
        actual=cases.placed(cases.poses()['attached'])
        wrong=copy.deepcopy(actual);wrong['centreOfMass']=cases.apply(cases.matrix(cases.BODY),actual['centreOfMass'])
        with self.assertRaises(AssertionError):qualifier.check_shape(wrong,actual)

    def test_selected_body_layout_does_not_change_local_mass_or_component_pose(self):
        seven=cases.local(7);nine=cases.local(9)
        self.assertAlmostEqual(nine['volume']/seven['volume'],9/7)
        self.assertEqual(cases.poses(7)['fixed'],cases.poses(9)['fixed'])
        delta=[cases.poses(9)['attached'][i][3]-cases.poses(7)['attached'][i][3] for i in range(3)]
        self.assertAlmostEqual(delta[2],0)
        self.assertGreater(abs(delta[0]),1)
        self.assertEqual(cases.local(),seven)
        changed=cases.document(body_frame=cases.CHANGED_BODY)
        for measurement in changed['measurements']:
            if 'edges' in measurement:self.assertEqual(measurement['edges']['where']['parallelTo'],[0,-1,0])

    def test_public_studio_template_instantiates_and_plans(self):
        from schemaxis.studio_library import load_library,instantiate_item
        library=load_library('freecad');item=next(t for t in library['templates'] if t['id']=='placed-body')
        document=instantiate_item(library,item,provider='freecad')
        self.assertEqual(document['nodes'][0]['options']['frame']['origin'],[7,-11,13])
        self.assertEqual(_native_plan(document)['parameters']['thickness']['value'],7)

    def test_failed_initial_submission_keeps_false_report_and_exact_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'proof'
            with patch.object(qualifier,'runtime_archive',return_value=b'test runtime'), \
                    patch.object(qualifier.registry,'run',side_effect=RuntimeError('first submission failed')):
                with self.assertRaisesRegex(RuntimeError,'first submission failed'):qualifier.qualify(out,sys.executable)
            report=json.loads((out/'report.json').read_text())
            self.assertFalse(report['verified']);self.assertEqual(report['failure']['phase'],'existing-seeded-WORLD-helper-regression')
            self.assertEqual(report['checks'],{})


if __name__=='__main__':unittest.main()
