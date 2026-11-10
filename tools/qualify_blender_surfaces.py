"""Run source-bound artist-surface qualifiers sequentially in one outer envelope."""
import argparse,json,subprocess,sys
from pathlib import Path
from blender_surface_evidence import identity,verify_identity

COMPONENTS={
    'normals':('normals',[]),'optics':('optics',[]),'channels':('channels',[]),
    'refraction-cycles':('refraction',[]),'refraction-eevee':('refraction',['--engine','eevee']),
    'displacement':('displacement',[]),'alpha-cycles':('alpha',[]),'alpha-eevee':('alpha',['--engine','eevee']),
    'authority':('authority',[]),'backends':('backends',[]),'projects':('projects',[]),'lifecycle':('lifecycle',[]),
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--components',nargs='+',choices=list(COMPONENTS),default=list(COMPONENTS));args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    report={'status':'running',**identity(out,args.blender),'requestedComponents':args.components,'components':[]};target=out/'summary.json'
    try:
        for name in args.components:
            family,extra=COMPONENTS[name];command=[sys.executable,str(Path(__file__).with_name('qualify_blender_surface_'+family+'.py')),
                '--blender',args.blender,'--output',str(out/name),*extra]
            report['activeComponent']=name;target.write_text(json.dumps(report,indent=2)+'\n');print(name+' START',flush=True)
            with (out/(name+'.log')).open('w') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
            summary=out/name/('report.json' if family=='normals' else 'summary.json')
            detail=json.loads(summary.read_text()) if summary.exists() else None
            item={'component':name,'exitCode':result.returncode,'summary':str(summary),'checks':len(detail.get('checks',[])) if detail else None,
                  'status':detail.get('status') if detail else 'missing'}
            report['components'].append(item);target.write_text(json.dumps(report,indent=2)+'\n')
            assert result.returncode==0 and detail and detail['status']=='passed',item
            for key in ('sourceFingerprint','runtimeArchiveSha256','runtimeBinarySha256'):assert detail[key]==report[key],(name,key)
            print(name+' PASS',flush=True)
        verify_identity(report,args.blender);report['status']='passed';report.pop('activeComponent',None)
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
