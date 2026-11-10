"""Bound expansion before planner hooks; no native application is invoked."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_service import ExecutionService
from schemaxis.mcp import McpDispatcher
from schemaxis.mcp_admission import FileAdmission, materialise_workflow
from schemaxis.tool_packages import _prepared
from test_mcp import POLYNOMIAL, request


def reference(name):
    return {'$document':'/definitions/'+name,'scope':'workflow'}


def dag(levels, leaf=0):
    definitions = {'a0':leaf}
    for index in range(1,levels+1):
        definitions['a'+str(index)] = [reference('a'+str(index-1)),reference('a'+str(index-1))]
    return {'version':'schemaxis.workflow/1','definitions':definitions,
            'operations':[{'id':'roots','document':copy.deepcopy(POLYNOMIAL)}]}


class WorkflowMaterialisationTests(unittest.TestCase):
    def denied(self, document):
        with self.assertRaises(SchemaxisError) as error:materialise_workflow(document)
        self.assertEqual(error.exception.fault.code,'MCP_POLICY_DENIED')

    def test_unused_metadata_fanout_refuses_before_dispatch_planner_and_capture(self):
        document=dag(30)
        with tempfile.TemporaryDirectory() as directory,ExecutionService(directory) as service:
            task=service.create_task('Bound materialisation',['sympy'])
            dispatcher=McpDispatcher(service)
            with patch('schemaxis.workflow.inspect_plan',side_effect=AssertionError('planner ran')):
                response=dispatcher.handle(request('tools/call',{'name':'plan','arguments':{
                    'task_id':task['id'],'document':document,'expected_revision':0}}))
            value=response['result']['structuredContent']
            self.assertFalse(value['ok'])
            self.assertEqual(value['fault']['code'],'MCP_POLICY_DENIED')
            self.assertEqual(service.task(task['id'])['revision'],0)
            self.assertEqual(service.state['plans'],{})

    def test_package_preflight_refuses_fanout_before_binder_hooks(self):
        bundle={'template':{'parameters':{}},'workflow':dag(30)}
        with patch('schemaxis.workflow_templates.bind_values',side_effect=AssertionError('binder ran')):
            with self.assertRaises(SchemaxisError) as error:_prepared(bundle,{},FileAdmission())
        self.assertEqual(error.exception.fault.code,'MCP_POLICY_DENIED')

    def test_repeated_large_strings_and_json_escape_overhead_are_bounded(self):
        self.denied(dag(8,'x'*16384))
        self.denied(dag(0,'\0'*180000))
        document=dag(0)
        document['definitions']['\0'*180000]=0
        self.denied(document)

    def test_direct_python_cycles_depth_and_non_json_values_refuse(self):
        values=[];values.append(values)
        self.denied(dag(0,values))
        value=0
        for _ in range(65):value=[value]
        self.denied(dag(0,value))
        class Untrusted:
            def __deepcopy__(self,memo):raise AssertionError('arbitrary object hook ran')
        for value in (Untrusted(),float('nan'),float('inf'),{'bad':set()}, {1:'nonstring key'}):
            with self.subTest(kind=type(value).__name__):self.denied(dag(0,value))

    def test_small_scalar_metadata_references_remain_admitted_and_independent(self):
        document=dag(1,'-2')
        document['operations'][0]['document']['coefficients'][2]=reference('a0')
        result=materialise_workflow(document)
        self.assertEqual(result['operations'][0]['document']['coefficients'],['1','0','-2'])
        self.assertEqual(result['definitions']['a1'],['-2','-2'])
        result['definitions']['a1'].append('changed')
        self.assertEqual(len(document['definitions']['a1']),2)
        FileAdmission().check(document)


if __name__=='__main__':unittest.main()
