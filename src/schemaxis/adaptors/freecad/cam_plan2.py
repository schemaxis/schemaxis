"""Internal named-tool CAM compiler; legacy plan/1 is deliberately unchanged."""
import copy
from schemaxis.documents import resolve_document
from schemaxis.errors import fail,keys
from schemaxis.pipeline import name
from .solid_source import source_record,vector as cad_vector
from .cam_drilling import number,operation as drilling,DIALECT
from . import cam_tools

VERSION='schemaxis.freecad.cam.plan/2'


def plan(document,*,captured=None,unread=False):
    document,_=resolve_document(copy.deepcopy(document))
    keys(document,('version','source','stock','tool','tools','operations','setup','quality','definitions','settings'),'$')
    if document.get('version')!='schemaxis.freecad.cam/1':fail('UNSUPPORTED_VERSION','Expected schemaxis.freecad.cam/1')
    if ('tool' in document)==('tools' in document):fail('INVALID_MACHINING','Declare either one tool or a named tools table','$')
    source=source_record(document.get('source'),captured=captured,unread=unread);bounds=source['bounds'];height=bounds[5]-bounds[4]
    raw=document.get('stock',{});keys(raw,('top','sides','bottom'),'$.stock')
    stock={k:number(raw.get(k,v),'$.stock.'+k,0,1000) for k,v in (('top',2),('sides',0),('bottom',0))}
    if stock['sides'] or stock['bottom']:fail('UNSUPPORTED_HOLDING','Use a pre-sized blank with zero side and bottom allowance','$.stock')
    origin=[(bounds[0]+bounds[1])/2,(bounds[2]+bounds[3])/2,bounds[5]+stock['top']]
    stock_bounds=[bounds[0]-origin[0],bounds[1]-origin[0],bounds[2]-origin[1],bounds[3]-origin[1],bounds[4]-origin[2],0]
    explicit='tools' in document
    tools=cam_tools.named(document['tools'],height+stock['top']) if explicit else cam_tools.single(document['tool'],height+stock['top'])
    raw=document.get('setup',{});keys(raw,('clearance','safe'),'$.setup')
    setup={k:number(raw.get(k,v),'$.setup.'+k,.1,1000) for k,v in (('clearance',5),('safe',3))}
    if setup['clearance']<setup['safe']:fail('INVALID_MACHINING','Clearance must be at or above the safe traverse plane','$.setup')
    raw=document.get('quality',{});keys(raw,('residualVolume','gougeVolume'),'$.quality')
    quality={k:number(raw.get(k,v),'$.quality.'+k,1e-5,1) for k,v in (('residualVolume',.1),('gougeVolume',.01))}
    raw=document.get('operations');operations=[];ids=set();faced=not stock['top']
    if not isinstance(raw,list) or not 1<=len(raw)<=16:fail('INVALID_MACHINING','Declare one to sixteen ordered machining operations','$.operations')
    for i,item in enumerate(raw):
        path='$.operations['+str(i)+']'
        if not isinstance(item,dict):fail('INVALID_MACHINING','Declare a typed machining operation',path)
        identity=name(item.get('id'),path+'.id');kind=item.get('operation')
        if identity in ids:fail('INVALID_MACHINING','Operation identities must be unique',path+'.id')
        ids.add(identity);tool=cam_tools.selected(tools,item,path,explicit=explicit)
        op={'id':identity,'operation':kind,'tool':tool['id']}
        if kind=='drill':
            if not faced:fail('INVALID_MACHINING','Face the top stock allowance before drilling',path)
            op.update(drilling(item,tool,bounds,origin,setup,path))
        elif kind in ('faceStock','pocket'):
            keys(item,('id','operation','tool','floor','stepDown','stepOver'),path)
            op.update(stepDown=number(item.get('stepDown',min(tool['diameter']/2,2)),path+'.stepDown',.01,min(tool['diameter'],height+stock['top'])),
                      stepOver=number(item.get('stepOver',.5),path+'.stepOver',.05,.8))
            if kind=='faceStock':
                if faced or i!=0 or 'floor' in item:fail('INVALID_MACHINING','Face the top allowance once, before other cuts; the target is the source top plane',path)
                op.update(start=0,finish=-stock['top']);faced=True
            else:
                if not faced:fail('INVALID_MACHINING','Face the top stock allowance before pocketing',path)
                floor=cad_vector(item.get('floor'),3,path+'.floor',code='INVALID_MACHINING')
                if not bounds[4]+1e-5<floor[2]<bounds[5]-1e-5 or not bounds[0]<floor[0]<bounds[1] or not bounds[2]<floor[1]<bounds[3]:
                    fail('INVALID_MACHINING','Select an interior point on an upward-facing pocket floor above the clamping base',path+'.floor')
                op.update(floor=floor,start=-stock['top'],finish=floor[2]-origin[2])
        else:fail('INVALID_MACHINING','Choose faceStock, pocket or drill',path+'.operation')
        operations.append(op)
    cam_tools.require_used(tools,operations)
    return {'version':VERSION,'source':source,'stock':stock,'origin':origin,'stockBounds':stock_bounds,
            'tools':tools,'setup':setup,'quality':quality,'operations':operations,'postprocessor':'linuxcnc',
            'units':'mm','frame':'stockTopCentre','cyclePolicy':DIALECT}
