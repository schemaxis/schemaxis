"""Finite semantic tools for compiled CAM2 jobs; no native imports or asset paths."""
import json
import uuid
from schemaxis.errors import fail,keys
from schemaxis.pipeline import name
from schemaxis.adaptors.freecad.solid_source import number

MAX_TOOLS=8
GEOMETRY=('diameter','cuttingLength','length','shankDiameter','flutes')
CUTTING=('rpm','feed','plunge')


def physical(raw,blank_height,path):
    keys(raw,(*GEOMETRY,*CUTTING),path)
    values={key:number(raw.get(key,default),path+'.'+key,lo,hi,code='INVALID_MACHINING')
            for key,default,lo,hi in (('diameter',None,.1,100),('cuttingLength',None,.1,1000),
                ('length',None,.1,2000),('shankDiameter',None,.1,100),('flutes',2,1,12),
                ('rpm',None,1,100000),('feed',None,.01,100000),('plunge',None,.01,100000))}
    if int(values['flutes'])!=values['flutes']:fail('INVALID_MACHINING','Flute count must be an integer',path+'.flutes')
    values['flutes']=int(values['flutes'])
    if (values['cuttingLength']<blank_height or values['length']<=values['cuttingLength']
            or values['shankDiameter']>values['diameter']):
        fail('UNSUPPORTED_TOOL_REACH','Use a centre-cutting flat endmill reaching the whole blank, with longer overall length and shank no wider than its cutter',path)
    return values


def compiled(identity,values,index):
    geometry={key:values[key] for key in GEOMETRY}
    marker=json.dumps({'id':identity,'kind':'flatEndmill','geometry':geometry},sort_keys=True,separators=(',',':'))
    return {'id':identity,'kind':'flatEndmill',**values,'number':index+1,
            'controller':'Cutter'+str(index),'nativeTool':'MillingTool'+str(index),
            'nativeId':str(uuid.uuid5(uuid.NAMESPACE_URL,'schemaxis.freecad.cam.tools/1/'+marker))}


def named(raw,blank_height):
    if not isinstance(raw,list) or not 1<=len(raw)<=MAX_TOOLS:fail('INVALID_MACHINING','Declare one to eight named tools','$.tools')
    result=[];identities=set()
    for index,item in enumerate(raw):
        path='$.tools['+str(index)+']';keys(item,('id','kind',*GEOMETRY,*CUTTING),path)
        identity=name(item.get('id'),path+'.id')
        if identity in identities:fail('INVALID_MACHINING','Named tool identities must be unique',path+'.id')
        if item.get('kind')!='flatEndmill':fail('UNSUPPORTED_TOOL','This compiler requires a qualified centre-cutting flatEndmill',path+'.kind')
        identities.add(identity)
        values=physical({k:v for k,v in item.items() if k not in ('id','kind')},blank_height,path)
        result.append(compiled(identity,values,index))
    return result


def single(raw,blank_height):
    return [compiled('cutter',physical(raw,blank_height,'$.tool'),0)]


def selected(tools,operation,path,*,explicit):
    if not explicit:
        if 'tool' in operation:fail('INVALID_MACHINING','Use a named tools table before selecting a tool per operation',path+'.tool')
        return tools[0]
    identity=name(operation.get('tool'),path+'.tool')
    matches=[tool for tool in tools if tool['id']==identity]
    if len(matches)!=1:fail('INVALID_MACHINING','Operation references an undeclared named tool',path+'.tool')
    return matches[0]


def require_used(tools,operations):
    used={operation['tool'] for operation in operations}
    expected={tool['id'] for tool in tools}
    if used!=expected:fail('INVALID_MACHINING','Every declared tool must be used by an operation','$.tools',unused=sorted(expected-used),undeclared=sorted(used-expected))


def template_record(tool):
    params={prop:str(tool[key])+' mm' for prop,key in (('Diameter','diameter'),('CuttingEdgeHeight','cuttingLength'),('Length','length'),('ShankDiameter','shankDiameter'))}
    params.update(Flutes=tool['flutes'],Material='HSS',SpindleDirection='Forward')
    return {'version':1,'name':tool['controller'],'nr':tool['number'],
            'tool':{'version':2,'id':tool['nativeId'],'name':tool['nativeTool'],'shape':'endmill','shape-type':'Endmill','parameter':params}}
