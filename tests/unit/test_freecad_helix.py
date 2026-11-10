"""Helix dimensional intent, reference ownership and persistent-driver admission."""
import copy,math,unittest
from schemaxis.adaptors.freecad import adaptor,helix
from schemaxis.core.faults import SchemaxisError


def design(options=None):
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'body','filter':'body'},
        {'id':'wire','filter':'circle','options':{'radius':1,'centre':[8,0],'plane':'XZ'},'inputs':{'body':'body'}},
        {'id':'coil','filter':'additiveHelix','options':options or {'pitch':6,'height':18},
         'inputs':{'body':'body','profile':'wire'}}],'output':'coil'}


class HelicalMaterial(unittest.TestCase):
    def fault(self,document,code):
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(document)
        self.assertEqual(caught.exception.fault.code,code)

    def test_modes_are_alternative_independent_dimensions(self):
        for options in ({'pitch':6,'height':18},{'mode':'pitchTurns','pitch':6,'turns':3},
                {'mode':'heightTurns','height':18,'turns':3},
                {'mode':'heightTurnsGrowth','height':18,'turns':3,'growth':0}):
            document=design(options);original=copy.deepcopy(document);planned=adaptor.plan(document)
            self.assertEqual(document,original)
            values=helix.settings(planned['nodes'][2]['options'])
            self.assertEqual([values[k] for k in ('pitch','height','turns','angle','growth')],[6,18,3,0,0])
            self.assertTrue(values['hasBeenEdited']);self.assertEqual(values['tolerance'],.1)
        for options in ({'pitch':6},{'pitch':6,'height':18,'turns':3},
                {'mode':'pitchTurns','height':18,'turns':3},
                {'mode':'heightTurnsGrowth','height':0,'turns':3,'growth':0},
                {'mode':'heightTurnsGrowth','height':18,'turns':3,'growth':1,'angle':1}):
            self.fault(design(options),'INVALID_HELIX_EXTENT')

    def test_cone_and_flat_spiral_derived_values_have_defined_units(self):
        options=adaptor.plan(design({'pitch':6,'height':18,'angle':10}))['nodes'][2]['options']
        self.assertAlmostEqual(helix.settings(options)['growth'],6*math.tan(math.radians(10)))
        options=adaptor.plan(design({'mode':'heightTurnsGrowth','height':0,'turns':3,'growth':2}))['nodes'][2]['options']
        self.assertEqual([helix.settings(options)[k] for k in ('pitch','height','angle','growth')],[0,0,0,2])
        self.fault(design({'pitch':.001,'height':100000}),'INVALID_HELIX_EXTENT')

    def test_reference_axis_profile_and_tip_must_belong_to_one_body(self):
        document=design();document['nodes'].insert(0,{'id':'other','filter':'body'})
        document['nodes'].insert(1,{'id':'otherAxis','filter':'datumAxis','inputs':{'body':'other'}})
        document['nodes'][-1]['inputs']['axis']='otherAxis';self.fault(document,'INVALID_BODY_OWNERSHIP')
        document=design();document['nodes'].append(copy.deepcopy(document['nodes'][2]));document['nodes'][-1]['id']='second'
        document['nodes'][-1]['inputs']['base']='coil';self.fault(document,'INVALID_BODY_OWNERSHIP')
        document=design();document['nodes'][2]['filter']='subtractiveHelix';self.fault(document,'INVALID_DEPENDENCY')

    def test_driven_primary_length_survives_planning_but_derived_length_is_refused(self):
        document=design({'mode':'pitchTurns','turns':3})
        document['parameters']={'lead':{'kind':'length','value':6,'minimum':4,'maximum':8}}
        document['nodes'][2]['drive']={'pitch':{'terms':{'lead':1}}}
        planned=adaptor.plan(document);self.assertEqual(planned['nodes'][2]['options']['pitch'],6)
        self.assertEqual(helix.settings(planned['nodes'][2]['options'])['height'],18)
        document['nodes'][2]['drive']={'height':{'terms':{'lead':1}}};self.fault(document,'INVALID_HELIX_EXTENT')

    def test_native_paths_and_kernel_policy_are_not_authored_options(self):
        for key,value in [('ReferenceAxis','Z_Axis'),('Tolerance',1),('tolerance',1),('Midplane',True)]:
            document=design();document['nodes'][2]['options'][key]=value;self.fault(document,'UNKNOWN_ARGUMENT')


if __name__=='__main__':unittest.main()
