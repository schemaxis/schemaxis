"""Pure staged-slot policy checks; no captures/native runtimes are opened."""
import copy
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_inputs import CapturedInput, InputBindings, bind_document
from schemaxis.mcp_admission import FileAdmission


DOCUMENTS = {
    'numpy': {'version':'schemaxis.numpy/1','operation':'principalComponents','source':'upload-one',
              'channels':[{'name':'a','unit':'mV'},{'name':'b','unit':'mV'}],
              'scaling':'none','retention':{'components':1}},
    'exiftool': {'version':'schemaxis.exiftool/1','operation':'editMetadata',
                'media':{'items':[{'id':'photo','path':'upload-one'}]},
                'edits':{'title':{'set':'An exact metadata value'}}},
    'ffmpeg': {'version':'schemaxis.ffmpeg/1','nodes':[{'id':'audio','filter':'encodeAudio',
               'options':{'file':'upload-one','bitrateKbps':96,'maxBytes':131072,'maxMeanPCMError':1200,'threads':1}}]},
}
SLOTS = {'numpy':('/source','.csv'), 'exiftool':('/media/items/0/path','.png'),
         'ffmpeg':('/nodes/0/options/file','.wav')}


def inputs(app):
    pointer,suffix = SLOTS[app]
    # Intentionally nonexistent: admission may inspect this trusted descriptor,
    # but must never read it. CapturePolicy later proves bytes and ownership.
    capture = CapturedInput('upload-one',Path('/unmounted-task-captures/task-one/upload-one'+suffix),
                            'sha256:'+'a'*64,20,1,2)
    return InputBindings('task-one',(capture,),((pointer,capture.identity),))


class StagedInputAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.admission = FileAdmission()

    def denied(self, document, context=None, **kwargs):
        with self.assertRaises(SchemaxisError) as error:
            self.admission.check(document,context,**kwargs)
        self.assertEqual(error.exception.fault.code,'MCP_POLICY_DENIED')

    def test_exact_opaque_slots_then_exact_stable_paths_admit_without_reading_inputs(self):
        from schemaxis.adaptors import registry
        with patch.object(registry,'plan',side_effect=AssertionError('planner ran')), \
             patch.object(registry,'binding',side_effect=AssertionError('route hook imported')):
            for app,document in DOCUMENTS.items():
                with self.subTest(app=app):
                    context = inputs(app)
                    admitted = self.admission.check(document,context)
                    self.assertEqual(admitted.routes,(document['version'],))
                    bound = bind_document(document,context)
                    self.assertEqual(self.admission.check(bound,context,bound=True),admitted)
                    self.denied(document)
                    self.denied(bound,context)
                    self.denied(document,context,bound=True)
                    self.denied(bound)
                    self.denied(document,{'namespace':'task-one','slots':context.slots})

    def test_creation_metadata_reuses_policy_and_rejects_raw_paths_before_capture(self):
        for app,document in DOCUMENTS.items():
            slots = self.admission.input_slots(document)
            self.assertEqual(len(slots),1)
            self.assertEqual(slots[0].pointer, SLOTS[app][0])
            self.assertIn(SLOTS[app][1], slots[0].suffixes)
            self.assertGreater(slots[0].max_bytes,0)
            context = inputs(app)
            with self.assertRaises(SchemaxisError):
                self.admission.input_slots(bind_document(document,context))
            with self.assertRaises(SchemaxisError):
                self.admission.input_slots({**document,'executable':'/outside'})
        self.assertEqual(self.admission.input_slots({'version':'schemaxis.sympy/1',
            'operation':'isolateRealRoots','coefficients':['1','0','-2']}),())

    def test_closed_schema_rejects_paths_code_auxiliary_sources_and_execution_overrides(self):
        for app,original in DOCUMENTS.items():
            for field in ('file','executable','command','code','execution','bindings'):
                document = {**copy.deepcopy(original),field:'/outside/forbidden'}
                with self.subTest(app=app,field=field):self.denied(document,inputs(app))
        document = copy.deepcopy(DOCUMENTS['exiftool'])
        document['media']['items'][0]['sidecar'] = '/outside/private.xmp'
        self.denied(document,inputs('exiftool'))
        document = copy.deepcopy(DOCUMENTS['exiftool'])
        document['media']['folder'] = {'path':'/outside'}
        self.denied(document,inputs('exiftool'))
        document = copy.deepcopy(DOCUMENTS['exiftool'])
        document['operation'] = 'copyMetadata'
        self.denied(document,inputs('exiftool'))
        document = copy.deepcopy(DOCUMENTS['ffmpeg'])
        document['nodes'][0]['options']['filter_complex'] = 'movie=/outside'
        self.denied(document,inputs('ffmpeg'))
        document = copy.deepcopy(DOCUMENTS['ffmpeg'])
        document['nodes'][0]['filter'] = 'muxReview'
        self.denied(document,inputs('ffmpeg'))

    def test_closure_refuses_wrong_pointer_duplicate_unused_capture_wrong_suffix_and_size(self):
        for app,document in DOCUMENTS.items():
            context = inputs(app); capture = context.captures[0]
            cases = [replace(context,slots=(('/unknown',capture.identity),)),
                     replace(context,slots=context.slots*2),
                     replace(context,captures=context.captures+(replace(capture,identity='extra',path=Path('/other.csv'),inode=3),)),
                     replace(context,captures=(replace(capture,path=Path('/outside/input.py')),)),
                     replace(context,captures=(replace(capture,bytes=129*1024**2),)),
                     replace(context,captures=(replace(capture,sha256='not-a-digest'),)),
                     replace(context,captures=()), replace(context,namespace=''),
                     replace(context,slots=(('/nodes/00/options/file',capture.identity),))]
            for case in cases:
                with self.subTest(app=app,context=case):self.denied(document,case)

    def test_changed_contract_route_or_source_digest_refuses_staged_inputs(self):
        from schemaxis.adaptors import registry
        for app,document in DOCUMENTS.items():
            policies = copy.deepcopy(self.admission.policies)
            entry = policies[document['version']]
            member = next(iter(entry['files']));entry['files'][member] = '0'*64
            with self.assertRaises(SchemaxisError):FileAdmission(policies).check(document,inputs(app))
            policies = copy.deepcopy(self.admission.policies)
            policies[document['version']]['schema']['properties']['command'] = {'type':'string'}
            with self.assertRaises(SchemaxisError):FileAdmission(policies).check(document,inputs(app))
            route = registry.ADAPTORS[app]['routes'][document['version']]
            with patch.dict(route,{'schema':'unreviewed:hook'}):self.denied(document,inputs(app))

    def test_numeric_budgets_and_staged_workflow_context_fail_closed(self):
        for value in (True,float('nan'),float('inf'),-1,65536,10**1000):
            document = copy.deepcopy(DOCUMENTS['ffmpeg'])
            document['nodes'][0]['options']['maxMeanPCMError'] = value
            self.denied(document,inputs('ffmpeg'))
        for threads in (True,0,17,'1'):
            document = copy.deepcopy(DOCUMENTS['ffmpeg'])
            document['nodes'][0]['options']['threads'] = threads
            self.denied(document,inputs('ffmpeg'))
        workflow = {'version':'schemaxis.workflow/1','operations':[{'id':'a','document':DOCUMENTS['numpy']}]}
        self.denied(workflow,inputs('numpy'))
        self.denied(workflow)
        polynomial = {'version':'schemaxis.sympy/1','operation':'isolateRealRoots','coefficients':['1','0','-2']}
        self.admission.check(polynomial)
        self.denied(polynomial,inputs('numpy'))
        self.denied(polynomial,bound=True)
