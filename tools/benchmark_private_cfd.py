#!/usr/bin/env python3
"""Compare raw ParaView and Schemaxis slices of an existing private CFD case.

A serial post-processing equivalence smoke test, not a solver-validation or AI
trial. Source cases are never copied into the repository by this tool.
"""
import argparse
import json
from pathlib import Path
import shutil

from benchmark_workflows import native, locations, save, require, near, TEMPLATES


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case-file',type=Path,required=True)
    p.add_argument('--case-type',choices=('Reconstructed Case','Decomposed Case'),required=True)
    p.add_argument('--times',type=float,nargs='+',required=True)
    p.add_argument('--fractions',type=float,nargs='+',default=[.5,.505])
    p.add_argument('--config',type=Path,required=True);p.add_argument('--output-directory',type=Path,required=True)
    args=p.parse_args();require(args.case_file.is_file(),'case marker must exist')
    require(1<=len(args.times)<=4 and len(set(args.times))==len(args.times),'use 1–4 distinct times')
    require(1<=len(args.fractions)<=4 and len(set(args.fractions))==len(args.fractions) and all(0<f<1 for f in args.fractions),'use 1–4 interior fractions')
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    loc=locations(args.config);case={'family':'cfd','file':str(args.case_file.resolve()),'caseType':args.case_type,'times':args.times,'fractions':args.fractions}
    report={'passed':False,'kind':'private-cfd-native-equivalence','autonomousAIComparison':False,'source':case['file'],'caseType':args.case_type}
    try:
        info=native('case_info',case,directory,loc,directory/'metadata');report['sourceMetadata']=info
        require(all(t in info['times'] for t in args.times),'requested time absent')
        require({'U','p'}<=set(info['fields']),'U/p fields absent')
        case.update(xmin=info['bounds'][0],length=info['bounds'][1]-info['bounds'][0])
        ordinary=directory/'ordinary';ordinary.mkdir();native('cfd',case,ordinary,loc)
        from schemaxis import workflow
        doc={'version':'schemaxis.workflow/1','execution':{},'operations':[]}
        for ti,t in enumerate(args.times):
            for fi,f in enumerate(args.fractions):
                part=json.loads((TEMPLATES/'cfd.json').read_text());part['times']=[t]
                part['nodes'][0]['options'].update(file=case['file'],caseType=args.case_type)
                part['nodes'][2]['options']['origin'][0]=case['xmin']+f*case['length']
                doc['operations'].append({'id':f'slice-{ti}-{fi}','document':part})
        save(directory/'workflow.json',doc)
        result=workflow.execute(doc,directory/'native',locations={k:v for k,v in loc.items() if k!='pvbatch'},timeout=180)
        output=directory/'schemaxis';output.mkdir()
        for job in result['jobs']:
            receipt=json.loads((Path(job['directory'])/'verification.json').read_text())
            artifact=next(a for a in receipt['artifacts'] if a.get('identity',{}).get('kind')=='geometry')
            shutil.copyfile(artifact['file'],output/(job['operation']+'.vtp'))
        left=native('vtk_info',case,ordinary,loc,directory/'grade-ordinary');right=native('vtk_info',case,output,loc,directory/'grade-schemaxis')
        checks=[]
        for name,a in left.items():
            b=right[name];require(a['cells']==b['cells'] and a['cells']>0,'slice count differs')
            near(a['area'],b['area']);require(a['area']>0,'zero slice area')
            for x,y in zip(a['bounds'],b['bounds']):near(x,y)
            require(set(a['fields'])==set(b['fields'])=={'U','p'},'missing fields')
            for field in ('U','p'):
                # Ignore ordering when comparing tuple distributions. This checks
                # numeric equivalence, not independent physical correctness.
                aa=sorted(a['fields'][field]);bb=sorted(b['fields'][field]);require(len(aa)==len(bb),'field count differs')
                for x,y in zip(aa,bb):
                    require(len(x)==len(y),'field width differs')
                    for v,w in zip(x,y):near(v,w)
            checks.append({'file':name,'cells':a['cells'],'area':a['area'],'fields':['U','p']})
        report.update(passed=True,checks=checks,scope='Matching serial native post-processing; no convergence or physical-solution claim; source redistribution permission not established.')
    except Exception as error:
        report['error']=str(error)
        raise
    finally:save(directory/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
