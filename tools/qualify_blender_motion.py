"""Connected native motion/morph acceptance with independent scalar/geometry facts."""
import argparse
import copy
import json
import math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run


def close(found,expected):
    assert len(found)==len(expected)
    assert all(math.isclose(a,b,abs_tol=2e-5,rel_tol=1e-6) for a,b in zip(found,expected)),(found,expected)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',required=True);a=parser.parse_args()
    root=Path(__file__).resolve().parents[1];out=Path(a.output).absolute();out.mkdir(parents=True,exist_ok=False)
    baseline=json.loads((root/'examples/schemaxis/blender-motion-clips.json').read_text());results=[]
    r=run(baseline,out/'connected',executable=a.blender,timeout=240)
    prod=json.loads((out/'connected'/'verification.json').read_text())['states'][0]['production'];samples={s['frame']:s for s in prod['samples']}
    # Reference pose10 plus half of linear displacement2. Morph lifts last two
    # vertices by2, with one half-weight mask, plus a .5-unit relative-key delta. Absolute progress.5 is middle shape.
    close(samples[6]['objects']['piece']['bounds'],[11,13,0,2,0,2.5])
    close(samples[6]['objects']['absolute']['bounds'],[0,2,0,2,2,2])
    close(samples[6]['objects']['copy']['matrix'][0],[1,0,0,3])
    close(samples[6]['objects']['copy']['matrix'][1],[0,1,0,0])
    results.append({'case':'connected','result':r,'literalRelativeBounds':[11,13,0,2,0,2.5],'literalAbsoluteBounds':[0,2,0,2,2,2]})
    # Four blend modes use the same4-unit clip and declared10-unit reference pose.
    d=copy.deepcopy(baseline);p=d['production'];p['objects']=[{'id':b,'kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],'location':[10,0,0]} for b in ('REPLACE','ADD','SUBTRACT','MULTIPLY','fade','trim')];p['shapeKeys']=[];p['rigs']=[];p['clips']=p['clips'][:1];p['layers']=[];p['exports']=[];p['renderFrames']=[];d['visible']=['REPLACE']
    for blend in ('REPLACE','ADD','SUBTRACT','MULTIPLY'):
        p['layers'].append({'id':blend,'clip':'move','bindings':[{'target':'part','object':blend}],'influence':.5,'blend':blend})
    p['layers'].append({'id':'fade','clip':'move','bindings':[{'target':'part','object':'fade'}],'fadeIn':4,'fadeOut':4})
    p['layers'].append({'id':'trim','clip':'move','bindings':[{'target':'part','object':'trim'}],'sourceStart':3,'sourceEnd':9,'scale':2})
    p['currentFrame']=3
    r=run(d,out/'layers',executable=a.blender,timeout=180)
    prod=json.loads((out/'layers'/'verification.json').read_text())['states'][0]['production'];samples={s['frame']:s for s in prod['samples']}
    for frame,expected in [(1,[5,10,10,5]),(6,[6,11,9,15]),(11,[7,12,8,25])]:
        close([samples[frame]['objects'][b]['matrix'][0][3] for b in ('REPLACE','ADD','SUBTRACT','MULTIPLY')],expected)
    close([samples[3]['objects']['fade']['matrix'][0][3]],[5.4])
    close([samples[3]['objects']['trim']['matrix'][0][3]],[1.2])
    results.append({'case':'layers','result':r,'literalMidpointX':[6,11,9,15],'literalFadedX':5.4,'literalTrimmedX':1.2})
    # Shared clip actions layer in strict array order on one object.
    d=copy.deepcopy(baseline);p=d['production'];p['objects']=[{'id':'part','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],'location':[10,0,0]}];p['rigs']=[];p['shapeKeys']=[];p['clips']=p['clips'][:1];p['layers']=[];p['exports']=[];p['renderFrames']=[];d['visible']=['part']
    for index,(blend,weight) in enumerate([('REPLACE',.5),('ADD',.2),('SUBTRACT',.3)]):
        p['layers'].append({'id':'layer'+str(index),'clip':'move','bindings':[{'target':'part','object':'part'}],'blend':blend,'influence':weight})
    r=run(d,out/'ordered',executable=a.blender,timeout=180)
    prod=json.loads((out/'ordered'/'verification.json').read_text())['states'][0]['production'];samples={s['frame']:s for s in prod['samples']}
    close([samples[6]['objects']['part']['matrix'][0][3]],[5.8])
    results.append({'case':'orderedSharedActionLayers','result':r,'literalMidpointX':5.8})
    # Same normalized absolute clip can drive different numbers of native shapes.
    d=copy.deepcopy(baseline);p=d['production'];p['objects']=[o for o in p['objects'] if o['id']=='absolute'];other=copy.deepcopy(p['objects'][0]);other['id']='other';p['objects'].append(other)
    p['shapeKeys']=[m for m in p['shapeKeys'] if m['object']=='absolute'];other=copy.deepcopy(p['shapeKeys'][0]);other['object']='other';other['keys']=other['keys'][-1:];p['shapeKeys'].append(other);p['rigs']=[];p['clips']=[c for c in p['clips'] if c['id']=='absoluteMorph'];p['layers']=[l for l in p['layers'] if l['clip']=='absoluteMorph'];other=copy.deepcopy(p['layers'][0]);other['id']='other';other['bindings'][0]['object']='other';p['layers'].append(other);p['exports']=[];p['renderFrames']=[];d['visible']=['absolute','other']
    r=run(d,out/'normalized',executable=a.blender,timeout=180)
    prod=json.loads((out/'normalized'/'verification.json').read_text())['states'][0]['production'];samples={s['frame']:s for s in prod['samples']}
    for name in ('absolute','other'):close(samples[6]['objects'][name]['bounds'],[0,2,0,2,2,2])
    results.append({'case':'normalizedAcrossShapeCounts','result':r,'literalHalfwayZ':2})
    # Portable native asset retains full actions, shape keys and NLA strips.
    d={'version':'schemaxis.blender.production/1','id':'reused-motion','prepareOnly':True,'production':{'frameStart':1,'frameEnd':41,'currentFrame':6,'assets':[{'id':'model','file':str(out/'connected'/'0000.blend'),'format':'blend'}]}}
    r=run(d,out/'reused',executable=a.blender,timeout=180);results.append({'case':'nativeAssetReuse','result':r})
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
