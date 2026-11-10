"""Directional-independent Fresnel and metal references for artist layers."""
import argparse,copy,hashlib,json,math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from qualify_blender_render_policy import document,pixel,expected
from blender_surface_evidence import identity,verify_identity


def constant(value):return {'kind':'constant','value':value}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    archive=hashlib.sha256(runtime_archive()).hexdigest()
    report={'status':'running','sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':archive,'checks':[],
            'oracle':'Normal-incidence smooth-interface Fresnel F0=((ior-1)/(ior+1))^2 under unit white environment, black diffuse. Neutral IOR1 and tinted fully metallic controls. Standard sRGB; maximum 2 encoded byte error declared before execution.'}
    target=out/'summary.json'
    report.update(identity(out,args.blender))
    base=document();base['render'].update(samples=8,worldColour=[1,1,1],worldStrength=1,lightEnergy=0)
    base['production']['materialGraphs']=[]
    base['production']['surfaceMaterials']=[{'id':'surface','baseColour':constant([0,0,0]),'roughness':constant(0)}]
    cases=[]
    for ior in (1,1.5,2):
        d=copy.deepcopy(base);d['production']['surfaceMaterials'][0]['ior']=constant(ior)
        cases.append(('fresnel-'+str(ior),d,[((ior-1)/(ior+1))**2]*3))
    d=copy.deepcopy(base);s=d['production']['surfaceMaterials'][0]
    s.update(ior=constant(1),coat={'weight':constant(1),'roughness':constant(0),'ior':constant(1.5)})
    cases.append(('independent-coat-interface',d,[.04]*3))
    d=copy.deepcopy(base);s=d['production']['surfaceMaterials'][0];colour=[.04,.09,.25]
    s.update(metallic=constant(1),baseColour=constant(colour));cases.append(('metal-normal-reflectance',d,colour))
    try:
        for label,d,reference in cases:
            report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n')
            run(d,out/label,executable=args.blender,timeout=180)
            with location_context({'blender':args.blender}):assert verify(out/label)['verified']
            actual=pixel(out/label);wanted=expected(reference,0)
            result={'label':label,'independentLinearReference':reference,'expectedRGBA':wanted,'actualRGBA':actual}
            report['checks'].append(result);target.write_text(json.dumps(report,indent=2)+'\n')
            assert all(abs(a-b)<=2 for a,b in zip(actual,wanted)),result
            print(label+' PASS',flush=True)
        assert hashlib.sha256(runtime_archive()).hexdigest()==archive
        verify_identity(report,args.blender)
        report['status']='passed';report.pop('activeCase',None)
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
