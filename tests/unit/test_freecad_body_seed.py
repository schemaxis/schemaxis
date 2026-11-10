"""Body seeding preserves explicit local/world semantics and ordered ownership."""
import copy,unittest
from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.adaptors.freecad.body_seed import output_name
from schemaxis.adaptors.freecad.parameters import expected_expressions


def example():
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'casting','filter':'box','options':{'length':20,'width':12,'height':5,'origin':[3,4,5]}},
        {'id':'part','filter':'body','options':{'frame':{'origin':[7,8,9],'xAxis':[0,1,0],'normal':[0,0,1]}}},
        {'id':'seed','filter':'bodySeed','inputs':{'body':'part','source':'casting'}},
        {'id':'bore','filter':'circle','options':{'radius':1,'origin':[10,10,5]},'inputs':{'body':'part'}},
        {'id':'cut','filter':'pocket','inputs':{'base':'seed','profile':'bore'}}], 'output':'cut'}


class BodySeed(unittest.TestCase):
    def test_seed_source_pose_expression_and_world_publication_are_compiled(self):
        d=example();original=copy.deepcopy(d);p=_native_plan(d)
        self.assertEqual(d,original)
        self.assertEqual(p['partDesign']['seeds'],{'part':'casting'})
        self.assertEqual(p['partDesign']['bodies']['part'],{'members':['seed','bore','cut'],'tip':'cut'})
        self.assertEqual(expected_expressions(p['nodes'][2]),{'Placement':'N0.Placement'})
        self.assertEqual(output_name(p,'cut'),'N1')
        self.assertEqual(output_name(p,'seed'),'N2')

    def test_seed_cannot_branch_reseed_consume_body_member_or_follow_profile(self):
        for mutate,code in [
            (lambda d:d['nodes'].insert(4,{'id':'seed2','filter':'bodySeed','inputs':{'body':'part','source':'casting'}}),'INVALID_BODY_SEED'),
            (lambda d:d['nodes'].insert(2,{'id':'first','filter':'circle','inputs':{'body':'part'}}),'INVALID_BODY_SEED'),
            (lambda d:d['nodes'].append({'id':'other','filter':'bodySeed','inputs':{'body':'part','source':'cut'}}),'INVALID_BODY_SEED'),
            (lambda d:d['nodes'][4]['inputs'].update(base='casting'),'INVALID_BODY_OWNERSHIP')]:
            with self.subTest(code=code):
                d=example();mutate(d)
                with self.assertRaises(SchemaxisError) as caught:_native_plan(d)
                self.assertEqual(caught.exception.fault.code,code)

    def test_authored_property_expression_escape_refused(self):
        d=example();d['nodes'][2]['options']={'expression':'casting.Placement'}
        with self.assertRaises(SchemaxisError):_native_plan(d)

    def test_legacy_unchecked_shape_reader_cannot_enter_a_seeded_graph(self):
        d=example();d['nodes'][0]={'id':'casting','filter':'readSTEP','options':{'file':'unadmitted.brep'}}
        with self.assertRaises(SchemaxisError) as caught:_native_plan(d)
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_SOURCE')


if __name__=='__main__':unittest.main()
