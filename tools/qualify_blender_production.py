"""Bounded connected scene-production acceptance; use an explicit Blender runtime."""
import argparse
import copy
import json
import math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];directory=Path(a.output).absolute();directory.mkdir(parents=True,exist_ok=False)
    baseline=json.loads((root/'examples/schemaxis/blender-production.json').read_text())
    results=[]
    result=run(baseline,directory/'animated-asset',executable=a.blender,timeout=180)
    receipt=json.loads((directory/'animated-asset'/'verification.json').read_text());prod=receipt['states'][0]['production'];samples={s['frame']:s for s in prod['samples']}
    for frame,x in [(1,0),(6,2),(11,4)]:
        assert math.isclose(samples[frame]['objects']['box']['matrix'][0][3],x,abs_tol=1e-6)
        assert math.isclose(samples[frame]['objects']['copy']['matrix'][0][3],x,abs_tol=1e-6)
        assert samples[frame]['objects']['box']['bounds']==[x-1,x+1,-1,1,-1,1]
    results.append({'case':'animated-asset','result':result,'literalMotion':[0,2,4]})
    nodes=copy.deepcopy(baseline);spec=nodes['scenes'][0]['production'];spec['objects']=[o for o in spec['objects'] if o['id']!='copy'];spec['hierarchy']=[h for h in spec['hierarchy'] if h['object']!='copy'];spec['exports']=[{'id':'node-model','format':'ply','objects':['box'],'frame':6}];spec['renderFrames']=[]
    spec['geometryGraphs']=[{'id':'lift','nodes':[{'id':'source','kind':'input'},{'id':'move','kind':'transform','values':{'translation':[0,0,2]}},{'id':'result','kind':'output'}],'links':[{'from':{'node':'source','socket':'geometry'},'to':{'node':'move','socket':'geometry'}},{'from':{'node':'move','socket':'geometry'},'to':{'node':'result','socket':'geometry'}}]}]
    spec['geometryBindings']=[{'object':'box','graph':'lift'}]
    spec['compositor']={'id':'grade','nodes':[{'id':'render','kind':'render'},{'id':'expose','kind':'exposure','values':{'exposure':-1}},{'id':'result','kind':'output'}],'links':[{'from':{'node':'render','socket':'image'},'to':{'node':'expose','socket':'image'}},{'from':{'node':'expose','socket':'image'},'to':{'node':'result','socket':'image'}}]}
    nodes['scenes'][0]['prepareOnly']=False
    result=run(nodes,directory/'nodes',executable=a.blender,timeout=180)
    receipt=json.loads((directory/'nodes'/'verification.json').read_text());bounds=receipt['states'][0]['production']['samples'][1]['objects']['box']['bounds'];assert bounds==[1,3,-1,1,1,3],bounds
    results.append({'case':'nodes','result':result,'literalBounds':[1,3,-1,1,1,3]})
    rig=copy.deepcopy(baseline);spec=rig['scenes'][0]['production'];spec['objects']=[];spec['collections']=[];spec['hierarchy']=[];spec['tracks']=[{'object':'skeleton','bone':'root','channel':'location','keys':[{'frame':1,'value':[0,0,0]},{'frame':11,'value':[0,2,0]}]}];spec['rigs']=[{'id':'skeleton','bones':[{'id':'root','head':[0,0,0],'tail':[0,0,1]}]}];spec['skin']=[{'object':'box','rig':'skeleton','weights':[{'bone':'root','vertices':list(range(8)),'weight':1}]}];spec['exports']=[{'id':'deformed','format':'stl','objects':['box'],'frame':6}];spec['renderFrames']=[]
    result=run(rig,directory/'rig',executable=a.blender,timeout=180)
    receipt=json.loads((directory/'rig'/'verification.json').read_text());samples={s['frame']:s for s in receipt['states'][0]['production']['samples']}
    assert samples[6]['objects']['box']['bounds']==[-1,1,-1,1,0,2],samples[6]
    results.append({'case':'rig','result':result,'literalBounds':[-1,1,-1,1,0,2]})
    sim=copy.deepcopy(baseline);spec=sim['scenes'][0]['production'];spec['objects']=[];spec['collections']=[];spec['hierarchy']=[];spec['tracks']=[];spec['renderFrames']=[];spec['exports']=[];spec['rigidBodies']=[{'object':'box','mass':2,'shape':'BOX'}];spec['simulationFrames']=[1,6,11]
    sim['nodes'][1]['options']['centre']=[0,0,5]
    result=run(sim,directory/'rigid-body',executable=a.blender,timeout=180)
    receipt=json.loads((directory/'rigid-body'/'verification.json').read_text());samples={s['frame']:s for s in receipt['states'][0]['production']['samples']}
    z=[samples[f]['objects']['box']['matrix'][2][3] for f in (1,6,11)];assert z[0]==5 and z[0]>z[1]>z[2],z
    expected=5-.5*9.81*(10/24)**2;assert abs(z[2]-expected)<.06,(z,expected)
    results.append({'case':'rigid-body','result':result,'centresZ':z,'independentBallisticZ':expected})
    cloth=copy.deepcopy(baseline);spec=cloth['scenes'][0]['production'];spec['objects']=[{'id':'fabric','kind':'mesh','vertices':[[x,y,3] for y in range(3) for x in range(3)],'faces':[[y*3+x,y*3+x+1,(y+1)*3+x+1,(y+1)*3+x] for y in range(2) for x in range(2)],'material':'paint'}];spec['collections']=[];spec['hierarchy']=[];spec['tracks']=[];spec['renderFrames']=[];spec['exports']=[];spec['cloth']=[{'object':'fabric','pinVertices':[0,2]}];spec['simulationFrames']=[1,6,11]
    result=run(cloth,directory/'cloth',executable=a.blender,timeout=180)
    receipt=json.loads((directory/'cloth'/'verification.json').read_text());samples={s['frame']:s for s in receipt['states'][0]['production']['samples']}
    assert samples[1]['objects']['fabric']['bounds']==[0,2,0,2,3,3]
    assert samples[11]['objects']['fabric']['bounds'][4]<2.9,samples[11]
    results.append({'case':'cloth','result':result,'lastBounds':samples[11]['objects']['fabric']['bounds']})
    turn=copy.deepcopy(baseline);spec=turn['scenes'][0]['production'];spec['collections']=[];spec['hierarchy']=[];spec['tracks']=[];spec['objects']=[{'id':'copy','kind':'instance','source':'box','location':[4,0,0]}];spec['materialBindings']=[];spec['renderFrames']=[1,6,11];spec['exports']=[];spec['intents']=[{'id':'product','kind':'turntable','objects':['box','copy'],'angleDegrees':180}]
    turn['nodes'][1]['options']['centre']=[5,0,0]
    result=run(turn,directory/'turntable',executable=a.blender,timeout=180)
    receipt=json.loads((directory/'turntable'/'verification.json').read_text());intent=receipt['states'][0]['production']['intents'][0]
    assert intent['pivot']==[4.5,0,0],intent
    assert math.isclose(intent['samples'][1]['world']['box'][0][3],4.5,abs_tol=1e-5)
    assert math.isclose(intent['samples'][1]['world']['box'][1][3],.5,abs_tol=1e-5)
    results.append({'case':'turntable','result':result,'literalPivot':[4.5,0,0]})
    constrained=copy.deepcopy(baseline);spec=constrained['scenes'][0]['production'];spec['collections']=[];spec['hierarchy']=[];spec['tracks']=[];spec['renderFrames']=[];spec['exports']=[];spec['materialBindings']=[];spec['objects']=[{'id':'target','kind':'empty','location':[4,0,0]},{'id':'path','kind':'curve','points':[[0,0,0],[0,5,0]],'bevel':0}];spec['rigs']=[{'id':'rig','bones':[{'id':'root','head':[0,0,0],'tail':[0,0,1]}]}];spec['constraints']=[]
    from schemaxis.adaptors.blender.production import CONSTRAINTS
    for kind in CONSTRAINTS:
        if kind=='inverseKinematics':spec['constraints'].append({'id':kind,'object':'rig','bone':'root','kind':kind,'target':'target'})
        else:
            spec['objects'].append({'id':kind+'Owner','kind':'instance','source':'box','location':[4,0,0] if kind=='limitLocation' else [0,0,0]})
            spec['constraints'].append({'id':kind,'object':kind+'Owner','kind':kind,**({} if kind.startswith('limit') else {'target':'path' if kind=='followPath' else 'target'})})
    result=run(constrained,directory/'constraints',executable=a.blender,timeout=180)
    receipt=json.loads((directory/'constraints'/'verification.json').read_text());sample=receipt['states'][0]['production']['samples'][0]
    assert sample['objects']['copyLocationOwner']['matrix'][0][3]==4
    assert sample['objects']['limitLocationOwner']['matrix'][0][3]==1
    results.append({'case':'constraints','result':result,'reviewedConstraints':len(CONSTRAINTS),'literalCopyX':4,'literalLimitedX':1})
    (directory/'summary.json').write_text(json.dumps({'status':'passed','cases':results},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results)}))

if __name__=='__main__':main()
