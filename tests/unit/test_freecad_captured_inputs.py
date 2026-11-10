"""Pinned inputs stay at the two checked CAD import positions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from schemaxis import captured_inputs
from schemaxis.adaptors.freecad import adaptor
from schemaxis.adaptors.freecad.captured_inputs import accept_resource
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema_authoring import version_schema

REFERENCE={'$resource':'/snapshots/stock','digest':'a'*64,'member':'stock.stl'}


def example(name='freecad-body-stock.json'):
    return json.loads(Path('examples/schemaxis',name).read_text())


class CapturedImportTests(unittest.TestCase):
    def refused(self,document,pointer,resource):
        with self.assertRaises(SchemaxisError) as error:
            accept_resource(document,pointer,resource)
        self.assertEqual(error.exception.fault.code,'UNSUPPORTED_RESOURCE')

    def test_actual_adoption_consumption_matches_literal_typed_plan(self):
        for name in ('freecad-body-stock.json','freecad-body-step-stock.json'):
            with self.subTest(example=name),tempfile.TemporaryDirectory() as temporary:
                document=example(name);literal=adaptor.plan(document)
                pinned=captured_inputs.adopt(document['nodes'][0]['options']['file'],Path(temporary)/'snapshot')
                document['nodes'][0]['options']['file']=pinned['reference']
                consumed,evidence=captured_inputs.consume(document,'stock')
                checked=adaptor.plan(consumed)
                self.assertEqual(checked['nodes'][0]['source']['sha256'],literal['nodes'][0]['source']['sha256'])
                self.assertEqual({k:v for k,v in checked['nodes'][0]['source'].items() if k!='path'},
                                 {k:v for k,v in literal['nodes'][0]['source'].items() if k!='path'})
                self.assertEqual(evidence[0]['pointer'],'/nodes/0/options/file')
                self.assertEqual(evidence[0]['digest'],pinned['digest'])
                self.assertEqual(evidence[0]['policy']['artifactKind'],'cad')
                captured_inputs.recheck(document,'stock')

    def test_pointer_and_container_grammar_is_closed(self):
        resource={'kind':'file','member':'stock.stl','files':['stock.stl']}
        for pointer in ('nodes/0/options/file','/nodes/00/options/file','/nodes/+0/options/file',
                        '/nodes/-1/options/file','/nodes/٠/options/file','/nodes/１/options/file',
                        '/nodes/'+'1'*5000+'/options/file','/nodes/1/options/file',
                        '/nodes/0/options/units','/nodes/0/inputs/source','/nodes/0/options/file/child'):
            self.refused(example(),pointer,resource)
        for nodes in ({'0':example()['nodes'][0]},None,'nodes',[]):
            self.refused({'version':'schemaxis.freecad/1','nodes':nodes},'/nodes/0/options/file',resource)
        for node in ([],None,{'filter':[]},{'filter':'readSTEP'},{'filter':'box'},
                     {'filter':'importMesh','options':[]},{'filter':'importMesh','options':{}},
                     {'filter':'importSTEP','options':None}):
            self.refused({'version':'schemaxis.freecad/1','nodes':[node]},'/nodes/0/options/file',resource)
        self.refused({**example(),'version':'schemaxis.freecad.assembly/1'},'/nodes/0/options/file',resource)

    def test_only_complete_single_file_snapshots_are_admitted(self):
        for resource in ({'kind':'directory','member':'stock.stl','files':['stock.stl']},
                         {'kind':'files','member':'stock.stl','files':['stock.stl']},
                         {'kind':'file','member':None,'files':['stock.stl']},
                         {'kind':'file','member':'other.stl','files':['stock.stl']},
                         {'kind':'file','member':'stock.stl','files':['stock.stl','extra.FCStd']}):
            self.refused(example(),'/nodes/0/options/file',resource)

    def test_workflow_schema_and_consuming_reader_positions_agree(self):
        workflow=jsonschema.Draft202012Validator(version_schema('schemaxis.freecad/1',authored=True,artifact=True))
        standalone=jsonschema.Draft202012Validator(version_schema('schemaxis.freecad/1',authored=True))
        expanded=jsonschema.Draft202012Validator(version_schema('schemaxis.freecad/1'))
        for name in ('freecad-body-stock.json','freecad-body-step-stock.json'):
            document=example(name)
            self.assertTrue(workflow.is_valid(document))
            document['nodes'][0]['options']['file']=REFERENCE
            self.assertTrue(workflow.is_valid(document),list(workflow.iter_errors(document)))
            self.assertFalse(standalone.is_valid(document));self.assertFalse(expanded.is_valid(document))
        for node in ({'id':'raw','filter':'readSTEP','options':{'file':REFERENCE}},
                     {'id':'box','filter':'box','options':{'length':REFERENCE}},
                     {'id':'mesh','filter':'importMesh','options':{'file':'stock.stl','units':REFERENCE}}):
            document={'version':'schemaxis.freecad/1','nodes':[node],'output':node['id']}
            self.assertFalse(workflow.is_valid(document))

    def test_pins_bytes_and_typed_units_keep_their_existing_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            document=example();snapshot=Path(temporary)/'snapshot'
            adopted=captured_inputs.adopt(document['nodes'][0]['options']['file'],snapshot)
            document['nodes'][0]['options']['file']=adopted['reference']
            forged=copy.deepcopy(document);forged['nodes'][0]['options']['file']['digest']='0'*64
            with self.assertRaises(SchemaxisError) as changed:captured_inputs.consume(forged,'stock')
            self.assertEqual(changed.exception.fault.code,'INPUT_CHANGED')
            stock=snapshot/'data'/adopted['reference']['member'];stock.write_bytes(stock.read_bytes()+b' changed')
            with self.assertRaises(SchemaxisError):captured_inputs.consume(document,'stock')
        with tempfile.TemporaryDirectory() as temporary:
            document=example('freecad-body-step-stock.json')
            adopted=captured_inputs.adopt(document['nodes'][0]['options']['file'],Path(temporary)/'snapshot')
            document['nodes'][0]['options'].update(file=adopted['reference'],units='mm')
            consumed,_=captured_inputs.consume(document,'stock')
            with self.assertRaises(SchemaxisError):adaptor.plan(consumed)


if __name__=='__main__':unittest.main()
