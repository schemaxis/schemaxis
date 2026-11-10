"""Host-only physical evidence type controls; native authority is separate."""
import copy
import unittest
from schemaxis.adaptors.freecad.cam_checks3 import numeric,counters


class PhysicalEvidence(unittest.TestCase):
    def test_exact_semantic_types_do_not_hide_small_integer_edits(self):
        self.assertTrue(numeric({'number':1000000,'flag':True,'value':1.0},
                                {'number':1000000,'flag':True,'value':1.0}))
        for actual in (1000001,1000000.0,True):
            self.assertFalse(numeric({'number':actual},{'number':1000000}))
        self.assertFalse(numeric(False,0))
        self.assertFalse(numeric(1.0,1))
        self.assertTrue(numeric(1.0+1e-9,1.0))
        self.assertFalse(numeric(float('nan'),1.0))

    def test_every_work_counter_retains_exact_integral_type_and_inventory(self):
        record={'sweeps':2,'tracks':2,'motions':40,
                'work':{'booleans':11,'booleanFacePairs':532,'identityComparisons':2024}}
        self.assertEqual(counters(record),record)
        for name in record['work']:
            for value in (True,1.0,-1):
                altered=copy.deepcopy(record);altered['work'][name]=value
                with self.subTest(name=name,value=value),self.assertRaises(ValueError):counters(altered)
        for change in ({'foreign':1},{'booleans':1}):
            with self.assertRaises(ValueError):counters(dict(record,work=change))

    def test_ordered_work_and_transition_counts_are_closed_exact_integers(self):
        record={'method':'continuous-ordered-physical-stock','sweeps':2,'tracks':2,'motions':14,
                'events':17,'toolTransitions':2,'clearanceChecks':6,'temporalCredits':1,'reusedRapidMasks':0,
                'work':{'booleans':42,'nativeFacePairs':1074,'identityComparisons':3865,'distances':4}}
        expected={k:v for k,v in record.items() if k!='method'}
        self.assertEqual(counters(record),expected)
        for key in ('events','toolTransitions','clearanceChecks','temporalCredits','reusedRapidMasks'):
            for value in (True,1.0,-1):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    counters(dict(record,**{key:value}))
        with self.assertRaises(ValueError):
            counters(dict(record,work={'booleans':42,'booleanFacePairs':1074,'identityComparisons':3865}))
