"""Public physical-tool intent and captured-source handoff boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jsonschema
from schemaxis.adaptors.freecad import cam
from schemaxis.adaptors.freecad.solid_source import capture_source
from schemaxis.core.faults import SchemaxisError
from test_freecad_cam import document


def physical():
    d=document();d['setup']={'toolClearance':{'kind':'evolvingStock','minimumSeparation':.4}}
    flat=d.pop('tool');d['tools']=[dict(flat,id='mill',kind='flatEndmill'),
        {'id':'pilot','kind':'drill','diameter':3,'tipAngle':120,'cuttingReach':4.25,
         'length':10.5,'rpm':6000,'feed':300,'plunge':100,
         'holder':{'stickOut':5,'steps':[{'diameter':5.5,'length':4},{'diameter':7.5,'length':4}]}}]
    for op in d['operations']:op['tool']='mill'
    d['operations'].append({'id':'point','operation':'drill','tool':'pilot','bottom':3,
        'depthReference':'tip','locations':{'kind':'explicit','centres':[[5,5]]},
        'cycle':{'kind':'peck','peck':.193,'return':'retract'}})
    return d


class PhysicalRoute(unittest.TestCase):
    def test_explicit_policy_selects_physical_family_and_legacy_stays_exact(self):
        from schemaxis.adaptors.freecad.cam_plan3 import plan
        original=physical();snapshot=copy.deepcopy(original)
        compiled=cam.plan(original)
        self.assertEqual(original,snapshot);self.assertEqual(compiled,plan(original))
        self.assertEqual(compiled['version'],'schemaxis.freecad.cam.plan/3')
        self.assertAlmostEqual(compiled['tools'][1]['tipHeight'],3/2/(3**.5),places=12)
        legacy=document();self.assertEqual(cam.plan(legacy)['version'],'schemaxis.freecad.cam.plan/1')
        jsonschema.validate(original,cam.schema());jsonschema.validate(legacy,cam.schema())
        del original['setup']
        with self.assertRaises(SchemaxisError) as caught:cam.plan(original)
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_TOOL_REACH')

    def test_closed_schema_choices_and_selected_tool_depth_semantics(self):
        schema=cam.schema();jsonschema.Draft202012Validator.check_schema(schema)
        for policy in ({'kind':'aboveBlank','axialClearance':1},
                       {'kind':'evolvingStock','minimumSeparation':.4}):
            d=physical();d['setup']['toolClearance']=policy
            jsonschema.validate(d,schema)
        for change in (lambda d:d['setup']['toolClearance'].update(minimumSeparation=0),
                       lambda d:d['setup']['toolClearance'].update(axialClearance=1),
                       lambda d:d['tools'][1].update(flutes=2.5),
                       lambda d:d['tools'][1]['holder'].update(placement=[0,0,1]),
                       lambda d:d['operations'][-1].update(throughClearance=0)):
            d=physical();change(d)
            with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(d,schema)
        # The schema cannot infer which named tool an operation selects.
        d=physical();del d['operations'][-1]['depthReference'];jsonschema.validate(d,schema)
        with self.assertRaises(SchemaxisError) as caught:cam.plan(d)
        self.assertEqual(caught.exception.fault.code,'INVALID_MACHINING')

    def test_retired_source_reuse_and_forged_capture_cannot_read_before_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);d=physical();source=root/'original.step'
            source.write_bytes(Path(d['source']['file']).read_bytes());d['source']['file']=str(source)
            p=cam.plan(d);capture_source(p['source'],root)
            (root/'authored.json').write_text(json.dumps(d));(root/'plan.json').write_text(json.dumps(p))
            source.unlink()
            self.assertEqual(cam.retainedInputs(root,d),{str(source):p['source']['sha256']})
            p['source']['capture']='../../unadmitted.step';(root/'plan.json').write_text(json.dumps(p))
            # Actual independent re-admission must refuse before the public
            # caller can select or read any receipt-provided capture pathname.
            with patch.object(cam,'plan',side_effect=AssertionError('read before admission')):
                with self.assertRaises(SchemaxisError) as caught:cam.retainedInputs(root,d)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
