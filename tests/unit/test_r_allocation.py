"""R numeric-table missing/type boundary and malformed retained-evidence faults (host only)."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.r import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


def document():
    return json.loads((ROOT/'examples/schemaxis/r-regression.json').read_text())


def fault(call,*args):
    found=None
    try:call(*args)
    except SchemaxisError as error:found=error.fault.to_dict()
    return found


class RCellBoundaryTests(unittest.TestCase):
    def cell(self,scope,row,column,value):
        doc=document();doc[scope][row][column]=value
        return fault(adaptor.plan,doc)

    def test_missing_values_are_distinct_from_unsupported_types(self):
        for scope,row,column in (('training',1,0),('training',3,1),('heldout',0,1)):
            for value in (None,float('nan'),'NA','na','N/A','NaN','','  ','null'):
                found=self.cell(scope,row,column,value)
                self.assertEqual(found['code'],'MISSING_VALUE',(scope,value))
                self.assertEqual(found['location'],f'$.{scope}[{row}][{column}]')
                self.assertIn('complete',found['recovery']);self.assertIn('imput',found['recovery'])
                self.assertNotIn('arguments',found['location'])

    def test_text_and_boolean_cells_are_unsupported_never_coerced(self):
        for value in ('red','1.5','1e3',True,False,'true'):
            found=self.cell('training',2,0,value)
            self.assertEqual(found['code'],'UNSUPPORTED_VALUE_TYPE',value)
            self.assertEqual(found['location'],'$.training[2][0]')
            self.assertIn('numeric',found['recovery']);self.assertNotEqual(found['code'],'INVALID_ARGUMENT')

    def test_fault_names_the_variable_not_only_the_position(self):
        found=self.cell('training',0,1,None)
        self.assertEqual(found['observed']['variable'],'reading')
        self.assertEqual(self.cell('heldout',1,0,'x')['observed']['variable'],'temperature')

    def test_infinity_and_range_remain_invalid_argument_and_valid_zero_accepted(self):
        for value in (float('inf'),float('-inf'),2e9):
            self.assertEqual(self.cell('training',0,0,value)['code'],'INVALID_ARGUMENT',value)
        doc=document();doc['training'][1][0]=-0.0;self.assertEqual(adaptor.plan(doc)['rank'],2)

    def test_first_bad_cell_in_row_major_order_wins_and_structure_errors_stay_generic(self):
        doc=document();doc['training'][2][1]='x';doc['training'][1][0]=None
        self.assertEqual(fault(adaptor.plan,doc)['location'],'$.training[1][0]')
        doc=document();doc['training'][0]={'a':1}
        self.assertEqual(fault(adaptor.plan,doc)['code'],'INVALID_ARGUMENT')
        doc=document();doc['training']='abc'
        self.assertEqual(fault(adaptor.plan,doc)['code'],'INVALID_ARGUMENT')

    def test_documents_are_not_mutated_and_valid_plan_unchanged(self):
        doc=document();saved=copy.deepcopy(doc);adaptor.plan(doc);self.assertEqual(doc,saved)


class RRetainedMalformationTests(unittest.TestCase):
    def verify(self,files):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/'run';directory.mkdir()
            for name,value in files.items():(directory/name).write_bytes(value if isinstance(value,bytes) else value.encode())
            try:adaptor.verify(directory)
            except SchemaxisError as error:return error.fault.to_dict()
        self.fail('verify unexpectedly passed')

    def test_deeply_nested_retained_json_is_a_structured_fault(self):
        found=self.verify({'authored.json':'['*100000+']'*100000,'verification.json':'{}'})
        self.assertEqual(found['code'],'VERIFICATION_FAILED')

    def test_unplannable_retained_authored_input_is_malformed_evidence_not_input_fault(self):
        text=(ROOT/'examples/schemaxis/r-regression.json').read_text().replace('6.1','NaN')
        found=self.verify({'authored.json':text,'verification.json':'{}'})
        self.assertEqual(found['code'],'VERIFICATION_FAILED');self.assertEqual(found['location'],'authored.json')
        self.assertEqual(found['observed']['authoredFault']['code'],'MISSING_VALUE')
        self.assertEqual(found['observed']['authoredFault']['location'],'$.training[0][1]')

    def test_absent_and_non_object_evidence_remain_distinct_verification_failures(self):
        self.assertEqual(self.verify({})['location'],'authored.json')
        self.assertEqual(self.verify({'authored.json':'[]'})['message'],'expected evidence object')


if __name__=='__main__':
    unittest.main()
