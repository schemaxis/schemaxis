#!/usr/bin/env python3
"""Qualify directed Graphviz topology, geometry, hostile evidence and workflow reuse."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shlex
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify,register
from schemaxis.adaptors.graphviz import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow
ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try:action()
    except SchemaxisError as e:
        assert e.fault.code==code,e.fault.to_dict();return e.fault.to_dict()
    raise AssertionError('hostile input/evidence was accepted')


def refresh(directory):
    directory=Path(directory).absolute()
    receipt=a.read(directory,'verification.json');receipt['artifacts']=a.artifacts(directory)
    receipt['evidence']={n:a.digest(directory,n) for n in receipt['evidence']};atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def literal_native(directory,name):
    """Separately parse native records; expected membership is literal, not layout.json."""
    records=[shlex.split(line) for line in (directory/'graph.plain').read_text().splitlines()]
    observed_nodes=[(r[1],r[6]) for r in records if r[0]=='node'];observed_edges=[r[1:3] for r in records if r[0]=='edge']
    expected_nodes=[('extract','Extract 01'),('build','Build'),('check','Check'),('publish','Publish')]
    expected_edges=[['extract','build'],['extract','check'],['build','publish'],['check','publish']]
    if name=='variant':expected_nodes+=[('archive','Archive 02')];expected_edges+=[['publish','archive']]
    if name=='cycle':expected_edges+=[['publish','extract']]
    assert sorted(observed_nodes)==sorted(expected_nodes) and len(observed_nodes)==len(expected_nodes)
    assert sorted(observed_edges)==sorted(expected_edges) and len(observed_edges)==len(expected_edges)
    centres={r[1]:(float(r[2]),float(r[3])) for r in records if r[0]=='node'}
    if name=='baseline':assert centres=={'extract':(2.625,2.25),'build':(1.25,1.25),'check':(4,1.25),'publish':(2.625,.25)}
    if name!='cycle':
        for source,target in expected_edges:
            if name=='left-right':assert centres[source][0]<centres[target][0]
            else:assert centres[source][1]>centres[target][1]
    return {'nodeIds':[n[0] for n in expected_nodes],'edgePairs':expected_edges,'literalLabels':True,'baselineCentresExact':name=='baseline'}


def hostile(directory):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()};report={}
    def restore():
        for p,b in saved.items():p.write_bytes(b)
    mutations=[('hiddenNode','graph.svg',lambda b:b.replace(b'class="node"',b'class="node" opacity="0"',1)),
        ('numericLabelDisappears','graph.svg',lambda b:b.replace(b'Extract 01</text>',b'Extract </text>')),
        ('overlayRectangle','graph.svg',lambda b:b.replace(b'</svg>',b'<rect width="9999" height="9999" fill="white"/></svg>')),
        ('svgSplineGeometry','graph.svg',lambda b:b.replace(b'M164.27',b'M164.99',1)),
        ('plainEndpointMembership','graph.plain',lambda b:b.replace(b'edge extract build',b'edge check build',1)),
        ('plainBoxOverlap','graph.plain',lambda b:b.replace(b'node build 1.25 1.25',b'node build 2.625 2.25',1)),
        ('dotNativeURL','graph.dot',lambda b:b.replace(b'"extract" [label=',b'"extract" [URL="file:///untrusted", label=',1)),
        ('trustedLauncher','layout-launcher.py',lambda b:b.replace(b"'-Kdot'",b"'-Kneato'",1)),
        ('hostSummaryGeometry','layout.json',lambda b:b.replace(b'2.625',b'2.626',1))]
    for name,target,mutation in mutations:
        try:
            path=directory/target;before=path.read_bytes();changed=mutation(before);assert changed!=before,name;path.write_bytes(changed);refresh(directory)
            report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    for name,mutation in [('missingEvidence',lambda r:r['evidence'].pop('layout.stdout')),('extraEvidence',lambda r:r['evidence'].update({'extra.json':'0'*64})),('publicationMembership',lambda r:r['artifacts'].pop()),('runtimeIdentity',lambda r:r.update(runtime='16.1.0 forged'))]:
        try:
            receipt=a.read(directory,'verification.json');mutation(receipt);atomic_json(directory/'verification.json',receipt)
            report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    try:
        submission=a.read(directory,'layout-submission.json');submission['nativeCommand']=['/forged/dot'];atomic_json(directory/'layout-submission.json',submission);refresh(directory)
        report['commandBinding']=refused(lambda:a.verify(directory))['code']
    finally:restore()
    assert a.verify(directory)['verified'];return report


def lifecycle(directory,document):
    """Owned slow wrapper probes lifecycle only; this is not native Graphviz evidence."""
    wrapper=directory/'slow-runtime.py';marker=directory/'slow.pid'
    wrapper.write_text('#!'+sys.executable+'\nimport os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(30)\n');wrapper.chmod(0o700)
    report={}
    for action in ['timeout','cancel']:
        if marker.exists():marker.unlink()
        cancel=threading.Event()
        def trigger():
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
            if marker.exists():cancel.set()
        thread=threading.Thread(target=trigger,daemon=True) if action=='cancel' else None
        if thread:thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):
                report[action]=refused(lambda:a.run(document,directory/('inflight-'+action),executable=str(wrapper),timeout=8 if thread else .4),'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')['code']
        finally:
            if thread:thread.join(6)
        assert marker.exists(),'owned child not launched'
        try:os.kill(int(marker.read_text()),0)
        except ProcessLookupError:pass
        else:raise AssertionError('child survived '+action)
        assert a.read(directory/('inflight-'+action),'result.json')['status']=='failed'
    return report


def native_labels(directory,executable):
    document={'version':a.VERSION,'operation':'layout','nodes':[{'id':'graph','label':'0'},{'id':'node','label':'Build/Check (2)+3:OK'}],'edges':[{'source':'graph','target':'node'}]}
    target=directory/'numeric-reserved-word';a.run(document,target,executable=executable,timeout=30)
    records=[shlex.split(line) for line in (target/'graph.plain').read_text().splitlines()]
    assert [(r[1],r[6]) for r in records if r[0]=='node']==[('graph','0'),('node','Build/Check (2)+3:OK')]
    before=(target/'graph.svg').read_bytes()
    try:
        (target/'graph.svg').write_bytes(before.replace(b'>0</text>',b'></text>'));refresh(target);refused(lambda:a.verify(target))
    finally:(target/'graph.svg').write_bytes(before);refresh(target)
    assert a.verify(target)['verified'];return {'numericZeroVisibleLiteral':True,'reservedDOTKeywordsQuoted':True,'supportedPunctuationLiteral':True,'refreshedHashNumericDisappearanceRejected':True}



def native_limits(directory,executable):
    document={'version':a.VERSION,'operation':'layout','rankDirection':'LR',
        'nodes':[{'id':'n'+str(index),'label':str(index)} for index in range(200)],
        'edges':[{'source':'n'+str(index),'target':'n'+str(index+step)} for step in [1,2,3] for index in range(200-step)][:500]}
    target=directory/'maximum-budgets';a.run(document,target,executable=executable,timeout=30)
    records=[shlex.split(line) for line in (target/'graph.plain').read_text().splitlines()]
    node_records=[r for r in records if r[0]=='node'];edge_records=[r for r in records if r[0]=='edge']
    assert len(node_records)==200 and len(edge_records)==500
    assert {(r[1],r[6]) for r in node_records}=={('n'+str(n),str(n)) for n in range(200)}
    assert {(r[1],r[2]) for r in edge_records}=={(e['source'],e['target']) for e in document['edges']}
    assert a.verify(target)['verified'];return {'nodes':200,'edges':500,'direction':'LR','verified':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--graphviz',required=True,type=Path);parser.add_argument('--output-directory',required=True,type=Path);parser.add_argument('--register',action='store_true');args=parser.parse_args()
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False);locations={'graphviz':str(args.graphviz.resolve())};report={'verified':False}
    try:
        receipt=qualify(a.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=45)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtimes':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        report['literalNative']={name:literal_native(directory/'kit'/name,name) for name in ['baseline','left-right','variant','cycle']}
        report['hostile']=hostile(directory/'kit/baseline');report['labels']=native_labels(directory,locations['graphviz']);report['limits']=native_limits(directory,locations['graphviz'])
        document=json.loads((ROOT/'examples/schemaxis/graphviz-baseline.json').read_text());consumer=copy.deepcopy(document)
        consumer['rankDirection']={'$value':'producer','artifact':3,'path':'/rankDirection'}
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'producer','document':document},{'id':'consumer','document':consumer}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30);assert workflow.verify(directory/'workflow')['verified']
        downstream=next(j for j in first['jobs'] if j['operation']=='consumer');assert a.read(Path(downstream['directory']),'layout.json')['rankDirection']=='TB'
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert all(j['reused'] for j in second['jobs'])
        producer=next(j for j in second['jobs'] if j['operation']=='producer');cached=Path(producer['directory'])/'graph.svg';cached.write_bytes(cached.read_bytes()+b'\n')
        third=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert not any(j['reused'] for j in third['jobs']);assert workflow.verify(directory/'workflow')['verified']
        graph['operations'][0]['document']['rankDirection']='LR'
        refused(lambda:workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True),'RESUME_MISMATCH')
        changed=workflow.execute(graph,directory/'workflow-changed',locations=locations,timeout=30);assert workflow.verify(directory/'workflow-changed')['verified']
        downstream=next(j for j in changed['jobs'] if j['operation']=='consumer');assert a.read(Path(downstream['directory']),'layout.json')['rankDirection']=='LR'
        report['workflow']={'status':first['status'],'verifiedValueHandoff':True,'unchangedReused':True,'corruptCachedProducerAndConsumerReused':False,'changedAuthoredResumeRejected':True,'freshChangedDirectionHandoff':'LR'}
        study=copy.deepcopy(document);study['axes']=[{'name':'direction','values':['TB','LR']}];study['rankDirection']={'$axis':'direction'}
        result=a.run(study,directory/'study',executable=locations['graphviz'],timeout=30);assert a.verify(directory/'study')['verified'] and len(result['states'])==2
        report['composition']={'states':2,'verified':True};report['inflightLifecycle']=lifecycle(directory,document)
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
