# Copyright (C) 2026 David L F Gaden
"""Reusable Schemaxis pipeline recipe: times x slice axis x appearances x cameras.

Usage: python3 schemaxis_recipe.py task.json submission
Uses installed/configured Schemaxis. Generated documents and complete run evidence
are retained beside publications; output paths are taken from artifact identities.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from schemaxis.adaptors.registry import run, verify


def document(task,case):
    axis=case['sliceAxis']; lengths=[case['length'],case['width'],case['height']]
    origins=[]
    for fraction in case['fractions']:
        origin=[0,0,0]; origin[axis]=fraction*lengths[axis]; origins.append(origin)
    normal=[0,0,0]; normal[axis]=1
    return {'version':'schemaxis/1','times':case['times'],
        'axes':[{'name':'cut','values':origins}],
        'nodes':[
            {'id':'source','filter':'pvPVDReader','options':{
                'FileName':str(Path(task['inputs'])/case['id']/'series.pvd'),
                'PointArrays':['T'],'CellArrays':['T']}},
            {'id':'slice','filter':'slice','inputs':{'input':'source'},
             'options':{'origin':{'$axis':'cut'},'normal':normal}}],
        'scenes':[{'id':'slices','geometry':['slice'],
            'visible':{'slice':task['appearances'][0]},
            'appearances':[{'slice':a} for a in task['appearances']],
            'images':[{'id':'view','size':task['imageSize'],
                       'cameras':[dict(c,parallel=True) for c in case['cameras']]}]}]}


def execute(task,output):
    from schemaxis.configuration import load
    for case in task['cases']:
        folder=output/case['id']; folder.mkdir(parents=True,exist_ok=True)
        doc=document(task,case)
        (folder/'pipeline.json').write_text(json.dumps(doc,indent=2)+'\n')
        # A unique attempt preserves failed evidence and lets revisions rerun.
        parent=Path(tempfile.mkdtemp(prefix='attempt-',dir=folder))
        target=parent/'run'
        run(doc,target,locations=load()['locations'],timeout=180)
        verify(target)
        receipt=json.loads((target/'verification.json').read_text())
        for artifact in receipt['artifacts']:
            identity=artifact['identity']
            stem=f"slice-{identity['timeIndex']}-{identity['indices']['cut']}"
            if identity['kind']=='geometry': name=stem+'.vtp'
            elif identity['kind']=='image':
                name=f"{stem}-appearance-{identity['appearance']}-camera-{identity['camera']}.png"
            else: continue
            shutil.copyfile(artifact['file'],folder/name)


if __name__=='__main__':
    execute(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2]))
