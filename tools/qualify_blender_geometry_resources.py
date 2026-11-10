"""Independent literal geometry effects of typed native resources and dependency guards."""
import argparse,copy,json
from pathlib import Path
from qualify_blender_mesh_data import close,native,production
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.errors import SchemaxisError


def base(kind='objectInfo',space='ORIGINAL',instance=False,separate=False,reset=False):
    inputs={'object':'selected','asInstance':instance} if kind=='objectInfo' else {'collection':'selected','separateChildren':separate,'resetChildren':reset}
    return {'version':'schemaxis.blender.production/1','prepareOnly':True,'visible':['target'],'production':{'objects':[{'id':'source','kind':'mesh','vertices':[[0,0,0],[2,0,0],[0,1,0]],'faces':[[0,1,2]],'location':[10,3,0],'collection':'parts'},{'id':'target','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],'location':[4,1,0]}],'collections':[{'id':'parts'}],'geometryResources':[{'id':'selected','kind':'object','object':'source'} if kind=='objectInfo' else {'id':'selected','kind':'collection','collection':'parts'}],'geometryGraphs':[{'id':'copy','nodes':[{'id':'source','kind':kind,'values':inputs,'properties':{'space':space}},{'id':'realise','kind':'realiseInstances'},{'id':'out','kind':'output'}],'links':[{'from':{'node':'source','socket':'geometry' if kind=='objectInfo' else 'instances'},'to':{'node':'realise','socket':'geometry'}},{'from':{'node':'realise','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]}],'geometryBindings':[{'object':'target','graph':'copy'}]}}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--blender',required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output.absolute();out.mkdir(parents=True);results=[];refusals=[]
    def execute(label,d,bounds,vertices=3):
        r=run(d,out/label,executable=a.blender,timeout=180);assert r['verified'];assert verify(out/label)['verified']
        obs=production(out/label)['samples'][0]['objects']['target'];close(obs['bounds'],bounds);assert obs['vertices']==vertices,(label,obs)
        results.append({'case':label,'literalBounds':bounds,'vertices':vertices,'result':r});print(label+' PASS',flush=True)
        (out/'summary.json').write_text(json.dumps({'status':'implementing','cases':results,'refusals':refusals},indent=2)+'\n')
    for space in ('ORIGINAL','RELATIVE'):
        for instance in (False,True):execute('object-'+space+'-'+str(instance),base(space=space,instance=instance),[4,6,1,2,0,0] if space=='ORIGINAL' else [10,12,3,4,0,0])
        for separate,reset in ((False,False),(True,False),(True,True)):
            expected=[4,6,1,2,0,0] if reset else ([14,16,4,5,0,0] if space=='ORIGINAL' else [10,12,3,4,0,0])
            execute('collection-'+space+'-'+str(separate)+'-'+str(reset),base('collectionInfo',space,separate=separate,reset=reset),expected)
    # A forwarded typed Object group input must preserve pointer identity and cost.
    d=base(space='RELATIVE');s=d['production'];g=s['geometryGraphs'][0];group=copy.deepcopy(g);group.update(id='reuse',family='geometry',inputs=[{'id':'prototype','kind':'object','default':'selected'}],outputs=[{'id':'geometry','kind':'geometry'}]);group['nodes'].insert(0,{'id':'in','kind':'input'});group['nodes'][1]['values']['object']='';group['links'].insert(0,{'from':{'node':'in','socket':'prototype'},'to':{'node':'source','socket':'object'}});s['nodeGroups']=[group];s['geometryGraphs']=[{'id':'copy','nodes':[{'id':'nested','kind':'group','group':'reuse','values':{'prototype':'selected'}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'nested','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]}]
    execute('group-resource-input',d,[10,12,3,4,0,0])
    # Source modifier dependency must be ordered by references, not binding list.
    d=base(space='RELATIVE');s=d['production'];s['geometryGraphs'].append({'id':'lift','nodes':[{'id':'in','kind':'input'},{'id':'move','kind':'setPosition','values':{'offset':[0,0,5]}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'move','socket':'geometry'}},{'from':{'node':'move','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}]});s['geometryBindings'].append({'object':'source','graph':'lift'});execute('modified-source',d,[10,12,3,4,5,5])
    def refuse(label,d,code):
        try:run(d,out/label,executable=a.blender,timeout=180)
        except SchemaxisError as e:
            assert code in str(e.fault.to_dict()),(label,e.fault.to_dict());refusals.append({'case':label,'fault':e.fault.to_dict()});print(label+' REFUSED',flush=True)
        else:raise AssertionError(label+' unexpectedly accepted')
    d=base();d['production']['geometryResources'][0]['object']='target';refuse('self-cycle',d,'DEPENDENCY_CYCLE')
    d=base('collectionInfo');d['production']['objects'][1]['collection']='parts';refuse('collection-self-cycle',d,'DEPENDENCY_CYCLE')
    d=base();d['production']['hierarchy']=[{'object':'source','parent':'target'}];refuse('parent-resource-cycle',d,'DEPENDENCY_CYCLE')
    d=base();s=d['production'];s['geometryResources'].append({'id':'consumer','kind':'object','object':'target'});reverse=copy.deepcopy(s['geometryGraphs'][0]);reverse['id']='reverse';reverse['nodes'][0]['values']['object']='consumer';s['geometryGraphs'].append(reverse);s['geometryBindings'].append({'object':'source','graph':'reverse'});refuse('mutual-cycle',d,'DEPENDENCY_CYCLE')
    d=base();g=d['production']['geometryGraphs'][0];g['nodes'].insert(0,{'id':'points','kind':'grid','values':{'xVertices':128,'yVertices':128}});g['nodes'].insert(1,{'id':'copies','kind':'instanceOnPoints'});g['links']=[{'from':{'node':'points','socket':'geometry'},'to':{'node':'copies','socket':'points'}},{'from':{'node':'source','socket':'geometry'},'to':{'node':'copies','socket':'instance'}},{'from':{'node':'copies','socket':'instances'},'to':{'node':'realise','socket':'geometry'}},{'from':{'node':'realise','socket':'geometry'},'to':{'node':'out','socket':'geometry'}}];# 3 source vertices alone fit; add a bounded source subdivision so actual cross-resource expansion refuses.
    s=d['production'];s['geometryGraphs'].append({'id':'expand','nodes':[{'id':'in','kind':'input'},{'id':'sub','kind':'subdivide','values':{'level':3}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'sub','socket':'mesh'}},{'from':{'node':'sub','socket':'mesh'},'to':{'node':'out','socket':'geometry'}}]});s['geometryBindings'].append({'object':'source','graph':'expand'});refuse('resource-instance-budget',d,'RESOURCE_BUDGET_EXCEEDED')
    d=base();s=d['production'];s['geometryResources']=[];s['geometryGraphs']=[];s['geometryBindings']=[];s['objects'][0]['uv']=[[[0,0],[1,0],[0,1]]];s['objects'][1]={'id':'target','kind':'instance','source':'source','location':[4,1,0]};s['meshData']=[{'object':'target','sharing':'shared','uvMaps':[{'name':'UVMap','method':'coordinates','coordinates':[[[0,0],[0,1],[1,1]]]}]}];refuse('legacy-uv-shared-alias',d,'INVALID_MESH_DATA')
    d=copy.deepcopy(d);d['production']['meshData'][0]['sharing']='copy';execute('legacy-uv-copy-isolation',d,[4,6,1,2,0,0])
    report={'status':'passed','cases':results,'refusals':refusals};(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results),'refusals':len(refusals)}))

if __name__=='__main__':main()
