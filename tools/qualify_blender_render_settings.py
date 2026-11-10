"""Native assignment and reopen matrix for the finite render policy."""
import argparse,json,subprocess
from pathlib import Path
from schemaxis.adaptors.blender.settings import render_settings


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False)
    cases=[('cycles',{}),('eevee',{'renderer':{'kind':'eevee','samples':1}}),
        ('screen-global',{'renderer':{'kind':'eevee','samples':1,'rayTracing':{'kind':'screen','quality':.7,'thickness':.2,'backfaces':{'kind':'singleSided'},'denoise':{'kind':'none'}},'fastGI':{'kind':'global','roughnessThreshold':.3,'distance':4,'thickness':.2,'bias':.1}}}),
        ('screen-ambient',{'renderer':{'kind':'eevee','samples':1,'rayTracing':{'kind':'screen','backfaces':{'kind':'bothSides','radianceReuse':.4},'denoise':{'kind':'filtered','temporal':False}},'fastGI':{'kind':'ambient','resolution':'4','quality':.8,'rays':3,'steps':12}}}),
        ('flat',{'renderer':{'kind':'workbench','lighting':{'kind':'flat'},'colourSource':{'kind':'single','colour':[.04,.09,.25]}}}),
        ('studio',{'renderer':{'kind':'workbench','lighting':{'kind':'studio','preset':'rim.sl','worldSpace':True,'rotation':.4},'shadows':{'kind':'on'},'cavity':{'kind':'both'},'outline':{'kind':'on'},'xray':{'kind':'on'},'backfaceCulling':True}}),
        ('matcap',{'renderer':{'kind':'workbench','lighting':{'kind':'matcap','preset':'clay_brown.exr'}}})]
    for view in ('standard','neutral','aces13','aces20','raw'):cases.append((view,{'colourManagement':{'view':{'kind':view},'exposure':.5,'gamma':1.2,'whiteBalance':{'kind':'on','temperature':4500,'tint':20}}}))
    for look in ('punchy','veryHigh','high','mediumHigh','mediumLow','low','veryLow'):cases.append((look,{'colourManagement':{'view':{'kind':'agx','contrast':look}}}))
    normalized=[(label,render_settings({**raw,'threads':2})) for label,raw in cases]
    (out/'cases.json').write_text(json.dumps(normalized,indent=2)+'\n')
    script='import sys,json\nfrom pathlib import Path\n'+f'sys.path.insert(0,{str(Path(__file__).resolve().parents[1]/"src")!r})\n'+'''import bpy
from schemaxis.adaptors.blender.native import configure_render,render_observation
from schemaxis.adaptors.blender.settings import matching
'''+f'out=Path({str(out)!r})\ncases=json.loads((out/"cases.json").read_text())\n'+'''report={'status':'running','checks':[]}
for label,settings in cases:
 bpy.ops.wm.read_factory_settings(use_empty=True);configure_render(bpy.context.scene,settings)
 assert matching(render_observation(),settings),(label,render_observation(),settings)
 file=out/(label+'.blend');bpy.ops.wm.save_as_mainfile(filepath=str(file),check_existing=False)
 bpy.ops.wm.open_mainfile(filepath=str(file),use_scripts=False)
 assert matching(render_observation(),settings),label
 report['checks'].append(label);(out/'summary.json').write_text(json.dumps(report,indent=2))
report['status']='passed';(out/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
'''
    path=out/'check.py';path.write_text(script);subprocess.run([a.blender,'--background','--factory-startup','--disable-autoexec','--threads','2','--python-exit-code','1','--python',str(path)],check=True,timeout=180)

if __name__=='__main__':main()
