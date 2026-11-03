#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native semantic finishing, independent solid oracles and analytic inspection."""
import argparse
import copy
import json
import math
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad.inspection import inspect
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--freecad-gui',type=Path,help='Optional dedicated live-session launcher')
    args=parser.parse_args();locations=json.loads(args.config.read_text())['locations']
    output=args.output_directory.absolute();output.mkdir(parents=True,exist_ok=False)
    doc=json.loads((ROOT/'examples/schemaxis/freecad-semantic-fillet.json').read_text())
    report={'verified':False,'scope':'Bounded geometric edge predicates and declared cardinality; no persistent topological identity claim.',
            'sourceDigest':source_digest('freecad'),'cases':{},'negative':{}}
    def run(name,document):
        target=output/name;registry.run(document,target,locations=locations,timeout=120)
        result=registry.verify(target);report['cases'][name]=result
        print(name,result,flush=True)
        return target
    def oracle(target,length,width,height,radius,kind='fillet'):
        area=length*width-((4-math.pi)*radius**2 if kind=='fillet' else 2*radius**2)
        perimeter=2*(length+width)-8*radius+(2*math.pi*radius if kind=='fillet' else 4*math.sqrt(2)*radius)
        receipt=json.loads((target/'verification.json').read_text())
        assert math.isclose(receipt['native']['volume'],area*height,rel_tol=1e-9,abs_tol=1e-7)
        assert math.isclose(receipt['native']['area'],2*area+height*perimeter,rel_tol=1e-9,abs_tol=1e-7)
        selected=receipt['selections']['rounded']
        assert len(selected['indices'])==4
        for index in selected['indices']:
            e=selected['edges'][index-1]
            assert e['curve']=='Line' and math.isclose(e['lengthMM'],height,abs_tol=1e-8)
            a,b=e['verticesMM'];assert math.isclose(a[0],b[0],abs_tol=1e-8) and math.isclose(a[1],b[1],abs_tol=1e-8)
        return receipt
    try:
        baseline=run('fillet',doc);oracle(baseline,20,10,5,1)
        variant=copy.deepcopy(doc);variant['nodes'][0]['options'].update(length=30,width=12,height=7,origin=[-3,4,5])
        target=run('translated-variant',variant);oracle(target,30,12,7,1)
        chamfer=copy.deepcopy(doc);chamfer['nodes'][1]['filter']='chamfer'
        chamfer['nodes'][1]['options'].pop('radius');chamfer['nodes'][1]['options']['distance']=1
        target=run('chamfer',chamfer);oracle(target,20,10,5,1,'chamfer')
        blank=copy.deepcopy(doc);blank['nodes'].pop();blank['output']='blank'
        source=run('source-solid',blank)
        imported=copy.deepcopy(doc);imported['nodes'][0]={'id':'blank','filter':'readSTEP','options':{'file':str(source/'model.step')}}
        target=run('imported-solid',imported);oracle(target,20,10,5,1)
        circular=copy.deepcopy(doc);circular['nodes'][0]={'id':'blank','filter':'cylinder','options':{'radius':5,'height':10}}
        circular['nodes'][1]['options']={'radius':.5,'edges':{'where':{'curve':'circle','onPlane':{'axis':'z','coordinate':10}},'expect':1}}
        target=run('circular-plane',circular)
        receipt=json.loads((target/'verification.json').read_text());selection=receipt['selections']['rounded']
        edge=selection['edges'][selection['indices'][0]-1]
        assert len(selection['indices'])==1 and edge['curve']=='Circle'
        assert math.isclose(edge['lengthMM'],2*math.pi*5,abs_tol=1e-8)
        assert all(math.isclose(v,10,abs_tol=1e-8) for v in edge['boundsMM'][4:])
        for label,where,count,code in [('empty',{'onPlane':{'axis':'z','coordinate':99}},1,'EMPTY_SELECTION'),
                                      ('ambiguous',{'parallelTo':[0,0,1]},1,'AMBIGUOUS_SELECTION'),
                                      ('missing',{'parallelTo':[0,0,1]},5,'SELECTION_COUNT_MISMATCH')]:
            bad=copy.deepcopy(doc);bad['nodes'][1]['options']['edges']={'where':where,'expect':count}
            try:registry.run(bad,output/label,locations=locations,timeout=120)
            except SchemaxisError as error:
                assert error.fault.code==code,error.to_dict();report['negative'][label]=error.to_dict()
            else:raise AssertionError(label+' selection unexpectedly succeeded')
        topology=copy.deepcopy(doc);node=copy.deepcopy(doc['nodes'][1]);node['id']='second';node['inputs']['base']='rounded'
        topology['nodes'].append(node);topology['output']='second'
        try:registry.run(topology,output/'changed-topology',locations=locations,timeout=120)
        except SchemaxisError as error:
            assert error.fault.code=='AMBIGUOUS_SELECTION',error.to_dict();report['negative']['changed-topology']=error.to_dict()
        else:raise AssertionError('changed topology silently accepted old cardinality')
        analytic=copy.deepcopy(doc);analytic['nodes'][0]['options']['height']={'$analytic':{'type':'values','values':[5,7]}}
        target=run('analytic',analytic)
        for i,h in enumerate((5,7)):oracle(target/('state-'+str(i).zfill(5)),20,10,h,1)
        observation=inspect(analytic,'blank',output/'inspection',executable=locations['freecad'],timeout=120,visit=1)
        assert observation['visit']==1 and math.isclose(observation['shape']['volume'],1400,abs_tol=1e-8)
        report['analyticInspection']={'visit':observation['visit'],'volume':observation['shape']['volume']}
        for filename in ('built.json','verification.json'):
            path=baseline/filename;original=path.read_bytes();value=json.loads(original)
            try:
                value['selections']['rounded']['indices']=[1];atomic_json(path,value)
                try:registry.verify(baseline)
                except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED'
                else:raise AssertionError('corrupt selection evidence was accepted')
            finally:path.write_bytes(original)
        registry.verify(baseline)
        envelope={'version':'schemaxis.workflow/1','operations':[{'id':'cad','document':doc}]}
        target=output/'workflow';workflow.execute(envelope,target,locations=locations,timeout=120)
        result=workflow.execute(envelope,target,locations=locations,timeout=120,resume=True)
        assert result['jobs'][0]['reused'];report['workflow']=workflow.verify(target)
        if args.freecad_gui:
            from schemaxis.adaptors.freecad.live import LiveSession
            with LiveSession(str(args.freecad_gui),output/'live',timeout=30,startup_timeout=30) as session:
                first=session.request('apply',document=doc)
                assert math.isclose(session.request('geometry')['volume'],(200-(4-math.pi))*5,abs_tol=1e-7)
                changed=copy.deepcopy(doc);changed['nodes'][0]['options']['height']=7
                second=session.request('apply',document=changed)
                before=session.request('geometry')
                assert first['pid']==second['pid'] and first['objects']==second['objects']
                assert math.isclose(before['volume'],(200-(4-math.pi))*7,abs_tol=1e-7)
                bad=copy.deepcopy(changed);bad['nodes'][1]['options']['edges']['expect']=1
                try:session.request('apply',document=bad)
                except SchemaxisError as error:assert error.fault.code=='AMBIGUOUS_SELECTION',error.to_dict()
                else:raise AssertionError('ambiguous live edit succeeded')
                assert session.request('geometry')==before
                assert session.request('status')['revision']==second['revision']
                report['live']={'verified':True,'pid':second['pid'],'reusedObjects':True,'ambiguityRollback':True}
        assert source_digest('freecad')==report['sourceDigest'],'source changed during qualification'
        report['verified']=True
    finally:atomic_json(output/'report.json',report)
    print('All semantic selection checks passed.',flush=True)


if __name__=='__main__':main()
