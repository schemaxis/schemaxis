# Copyright (C) 2026 David L. F. Gaden.
"""Serial public-host Data preservation across ordinary drafts and checked identity views."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from schemaxis.live_data import LiveDataSession
from schemaxis.storage import digest
from test_paraview_live_identity import TETRA, CountingProcess, archive


def exercise(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    first,third=directory/'first.ply',directory/'third.ply'
    first.write_text(TETRA.format(0,1));third.write_text(TETRA.format(10,11))
    old={'version':'schemaxis/1','nodes':[
        {'id':'mesh','filter':'readPLY','options':{'files':[str(first)]}},
        {'id':'skin','filter':'shrink','inputs':{'input':'mesh'},'options':{'factor':.5}},
        {'id':'third','filter':'readPLY','options':{'files':[str(third)]}}]}
    new=copy.deepcopy(old);new['nodes'].extend([
        {'id':'extra','filter':'shrink','inputs':{'input':'mesh'},'options':{'factor':.25}},
        {'id':'leaf','filter':'shrink','inputs':{'input':'extra'},'options':{'factor':.5}}])
    evidence={'steps':[]};CountingProcess.started=[]
    def request(value,view=None,**args):
        return {'input':value,'sessionDocument':'resident-document',**({'view':view} if view else {}),**args}
    with patch('schemaxis.live_transport.runtime_archive',archive), LiveDataSession(directory/'data',CountingProcess) as live:
        def record(label,value,view=None,node='mesh',owned=None,owned_view=None):
            origins_before=copy.deepcopy(next(iter(live.workers.values()))['evidence'])
            refreshed=live.refresh(request(value,view,nodes=[node],expression='extents('+node+')'))
            inspected={}
            for item in (node,'skin'):
                inspected[item]=live.inspect(request(value,view),item,geometry=True)
            extra_inspected={}
            owner_input=value if owned is None else owned
            owner_view=view if owned is None else owned_view
            for item in ('extra','leaf','fresh'):
                if any(n['id']==item for n in owner_input['nodes']):
                    extra_inspected[item]=live.inspect(request(owner_input,owner_view),item,geometry=True)
            client=CountingProcess.started[0]
            evidence['steps'].append({'label':label,'input':value,'view':view,'refresh':refreshed,
                'selection':live.selection(request(value,view)),'inspected':inspected,'requestedNode':node,
                'native':client.request('status'),'extraInspected':extra_inspected,
                'measurementOriginsBefore':origins_before,
                'measurementOriginsAfter':copy.deepcopy(next(iter(live.workers.values()))['evidence']),'factories':len(CountingProcess.started)})
        live.load(request(old,nodes=['skin']));record('initial',old)
        live.load(request(new,nodes=['skin','leaf']));record('new siblings',new)
        record('old bare after addition',old,owned=new)
        new=copy.deepcopy(new);new['nodes'][3]['options']['factor']=.75
        live.load(request(new,nodes=['leaf']));record('changed sibling',new)
        record('old bare after option',old,owned=new)
        preview=live.prepare_identity_transition(request(new),'/nodes/0/id','globe',digest(new))
        expected={k:preview['transition'][k] for k in ('inputDigest','outputDigest','policyDigest')}
        accepted=live.accept_identity_transition(request(new),'/nodes/0/id','globe',expected)
        compound=copy.deepcopy(accepted['input'])
        compound['nodes'].append({'id':'fresh','filter':'shrink','inputs':{'input':'globe'},'options':{'factor':.4}})
        evidence['pendingOrdinary']={'input':compound,'view':accepted['to'],
            'before':CountingProcess.started[0].request('status'),
            'originsBefore':copy.deepcopy(next(iter(live.workers.values()))['evidence'])}
        # First request after accepting the Name: no inspection or Refresh has aligned it.
        live.load(request(compound,accepted['to'],nodes=['fresh']))
        evidence['pendingOrdinary'].update(after=CountingProcess.started[0].request('status'),
            originsAfter=copy.deepcopy(next(iter(live.workers.values()))['evidence']),
            transition=copy.deepcopy(next(iter(live.workers.values()))['lastLoad']))
        accepted={**accepted,'input':compound}
        record('renamed current',accepted['input'],accepted['to'],'globe')
        record('old bare after rename',old,owned=accepted['input'],owned_view=accepted['to'])
        record('new named again',accepted['input'],accepted['to'],'globe')
        processes=[p.process for p in CountingProcess.started]
        evidence['archives']=[str(p.directory/'runtime.zip') for p in CountingProcess.started]
    evidence['exited']=[p.poll() for p in processes]
    return evidence


def assert_evidence(test,evidence):
    first=evidence['steps'][0];proxies=first['native']['harness']['proxies']
    skin=first['inspected']['skin']['geometry']['objects']
    for step in evidence['steps']:
        native=step['native'];names=native['harness']['proxies'];node='globe' if 'globe' in names else 'mesh'
        test.assertEqual(1,step['factories']);test.assertEqual(first['native']['pid'],native['pid'])
        test.assertEqual(proxies['mesh']['globalId'],names[node]['globalId'])
        test.assertEqual(proxies['skin']['globalId'],names['skin']['globalId'])
        test.assertEqual((1,1),(names[node]['executions'],names['skin']['executions']))
        test.assertNotIn('third',names)
        test.assertEqual(sorted([*names,'occupied']),native['harness']['registered'])
        test.assertEqual(skin,step['inspected']['skin']['geometry']['objects'])
        test.assertEqual([0,1,0,2,0,3],step['inspected'][step['requestedNode']]['observation']['bounds'])
        test.assertEqual((4,4),(step['inspected'][step['requestedNode']]['observation']['points'],step['inspected'][step['requestedNode']]['observation']['cells']))
        test.assertEqual(digest(step['input']),step['refresh']['observations']['inputDigest'])
        test.assertEqual('resolved',step['refresh']['records'][0]['state'])
        extra=step['extraInspected']
        if extra:
            changed=step['label'] not in ('new siblings','old bare after addition')
            for name,factor in (('extra',.75 if changed else .25),('leaf',.375 if changed else .125)):
                test.assertEqual(2 if changed else 1,names[name]['executions'])
                observation=extra[name]['observation']
                test.assertEqual((12,4),(observation['points'],observation['cells']))
                maximum=(1+2*factor)/3
                for actual,expected in zip(observation['bounds'],[0,maximum,0,2*maximum,0,3*maximum]):
                    test.assertAlmostEqual(expected,actual,places=6)
        if 'fresh' in extra:
            test.assertEqual(1,names['fresh']['executions'])
            observation=extra['fresh']['observation']
            test.assertEqual((12,4),(observation['points'],observation['cells']))
            for actual,expected in zip(observation['bounds'],[0,.6,0,1.2,0,1.8]):
                test.assertAlmostEqual(expected,actual,places=6)
        if step['label'].startswith('old bare'):
            # Namespace alignment carries each measured origin; readback cannot
            # replace it with the requesting old draft's recipe.
            before=sorted(step['measurementOriginsBefore'].values(),key=lambda x:x['name'])
            after=sorted(step['measurementOriginsAfter'].values(),key=lambda x:x['name'])
            test.assertEqual(before,after)
    pending=evidence['pendingOrdinary']
    test.assertIn('mesh',pending['before']['harness']['proxies'])
    test.assertNotIn('fresh',pending['before']['harness']['proxies'])
    test.assertIn('globe',pending['after']['harness']['proxies'])
    test.assertEqual(['fresh'],pending['transition']['created'])
    test.assertEqual(['fresh'],pending['transition']['updated'])
    test.assertEqual(pending['before']['owner']['generation']+2,pending['after']['owner']['generation'])
    test.assertEqual([0],evidence['exited'])


class NativePublicDataPreservation(unittest.TestCase):
    def test_public_old_and_new_windows_keep_one_selected_reader(self):
        from schemaxis.adaptors.paraview.mvp.runners import find_paraview
        if not find_paraview():self.skipTest('ParaView is not configured')
        with tempfile.TemporaryDirectory() as directory:assert_evidence(self,exercise(directory))
