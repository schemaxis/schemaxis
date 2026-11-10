"""Reusable typed node interfaces and closed per-domain group composition."""
from schemaxis.errors import fail,keys
from schemaxis.core.declarations import validate_arguments
from schemaxis.schema import object_schema,arguments_schema,argument_schema
from .node_catalogue import number,integer,boolean,vector,colour,text,socket,node

KINDS={
 'number':('NodeSocketFloat','number',number()),
 'integer':('NodeSocketInt','number',integer(0,minimum=-1000000,maximum=1000000)),
 'boolean':('NodeSocketBool','boolean',boolean()),
 'vector':('NodeSocketVector','vector',vector()),
 'colour':('NodeSocketColor','colour',colour()),
 'string':('NodeSocketString','string',text()),
 'rotation':('NodeSocketRotation','rotation',vector()),
 'matrix':('NodeSocketMatrix','matrix',None),
 'geometry':('NodeSocketGeometry','geometry',None),
 'shader':('NodeSocketShader','shader',None),
 'object':('NodeSocketObject','object',text()),
 'collection':('NodeSocketCollection','collection',text()),
 'material':('NodeSocketMaterial','material',text()),
 'image':('NodeSocketImage','image',text()),
}
COMMON={'number','integer','boolean','vector','colour'}
DOMAINS={'material':COMMON|{'shader'},'geometry':COMMON|{'geometry','string','rotation','matrix','object','collection','material','image'},
 'compositor':COMMON|{'image','string','rotation','matrix','object'}}
REFERENCE_KINDS={'object','collection','material','image'}
NAME={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$','maxLength':128}


def kind_descriptor(kind,family):
    if not isinstance(kind,str) or kind not in DOMAINS[family]:fail('TYPE_MISMATCH','interface kind is unavailable in this node domain',kind)
    if family=='compositor' and kind=='image':return ('NodeSocketColor','image',None)
    return KINDS[kind]


def value_spec(interface,family):
    _,_,spec=kind_descriptor(interface['kind'],family)
    if spec is None:return None
    spec={**spec,'default':interface['default']}
    if interface['kind'] in ('number','integer'):
        spec.update(minimum=interface['minimum'],maximum=interface['maximum'])
    return spec


def interface_ports(records,family,values=False):
    result={}
    for item in records:
        _,kind,_=kind_descriptor(item['kind'],family);spec=value_spec(item,family) if values else None
        result[item['id']]=socket(item['id'],kind,spec)
    return result


def descriptor(authored,family,groups=None,interface=None):
    from .node_catalogue import CATALOGUES
    kind=authored.get('kind')
    if not isinstance(kind,str):fail('UNSUPPORTED_NODE','node kind must be a reviewed identifier')
    if kind!='group' and 'group' in authored:fail('UNKNOWN_ARGUMENT','group reference belongs only to group instances')
    if interface and kind in ('input','output'):
        return node('NodeGroupInput',outputs=interface_ports(interface['inputs'],family)) if kind=='input' else node('NodeGroupOutput',inputs=interface_ports(interface['outputs'],family,True))
    if kind=='group':
        ref=authored.get('group')
        if not isinstance(ref,str):fail('UNKNOWN_REFERENCE','group requires a named interface')
        group=(groups or {}).get(ref)
        if not group:fail('UNKNOWN_REFERENCE','named node group is absent',authored.get('group'))
        if group['family']!=family:fail('TYPE_MISMATCH','node groups cannot cross shader, geometry and compositor domains',authored.get('group'))
        return node({'material':'ShaderNodeGroup','geometry':'GeometryNodeGroup','compositor':'CompositorNodeGroup'}[family],
          interface_ports(group['inputs'],family,True),interface_ports(group['outputs'],family))
    if kind not in CATALOGUES[family]:fail('UNSUPPORTED_NODE','choose a reviewed '+family+' node',str(kind))
    if 'group' in authored:fail('UNKNOWN_ARGUMENT','group reference belongs only to group instances')
    desc=CATALOGUES[family][kind]
    if family=='geometry' and kind=='namedAttribute':
        import copy
        from .mesh_data import CHANNELS
        desc=copy.deepcopy(desc)
        native=authored.get('properties',{}).get('dataType','FLOAT')
        desc['outputs']['attribute']['kind']=next((v[3] for v in CHANNELS.values() if v[0]==native),'number')
    return desc


def group_node_schema():
    # Interface socket IDs are user-defined. Semantic validation resolves these
    # names against closed typed declarations before any native assignment.
    scalar={'anyOf':[{'type':'number'},{'type':'boolean'},{'type':'string'},{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':4}]}
    return object_schema({'id':NAME,'kind':{'const':'group'},'group':NAME,
      'values':{'type':'object','maxProperties':64,'additionalProperties':scalar},'properties':object_schema({})},['id','kind','group'])


def schema_property():
    kinds=sorted(KINDS)
    interface=object_schema({'id':NAME,'kind':{'enum':kinds},'description':{'type':'string','maxLength':1024},
      'default':{'anyOf':[{'type':'number'},{'type':'boolean'},{'type':'string'},{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':4}]},
      'minimum':{'type':'number'},'maximum':{'type':'number'}},['id','kind'])
    endpoint=object_schema({'node':NAME,'socket':NAME},['node','socket'])
    # Native options remain finite at semantic admission. A generic declaration
    # avoids duplicating every reviewed constructor across three reusable domains.
    from .node_catalogue import CATALOGUES
    kinds=sorted(set().union(*(c for c in CATALOGUES.values()))|{'input','group'})
    field={'type':'object','additionalProperties':True,'maxProperties':64}
    graph_node=object_schema({'id':NAME,'kind':{'enum':kinds},'group':NAME,'values':field,'properties':field},['id','kind'])
    return {'type':'array','maxItems':128,'items':object_schema({'id':NAME,'family':{'enum':list(DOMAINS)},
      'inputs':{'type':'array','maxItems':64,'items':interface},'outputs':{'type':'array','minItems':1,'maxItems':64,'items':interface},
      'nodes':{'type':'array','minItems':1,'maxItems':256,'items':graph_node},'links':{'type':'array','maxItems':1024,'items':object_schema({'from':endpoint,'to':endpoint},['from','to'])}},['id','family','inputs','outputs','nodes','links'])}


def _interface(records,family,where,output=False):
    if not isinstance(records,list) or len(records)>64 or output and not records:fail('INVALID_NODE_GRAPH','interface requires bounded socket arrays and at least one output',where)
    result=[];seen=set()
    from schemaxis.pipeline import name
    for i,r in enumerate(records):
        loc=f'{where}[{i}]';keys(r,('id','kind','description','default','minimum','maximum'),loc);name(r.get('id'),loc+'.id')
        if r['id'] in seen:fail('DUPLICATE_ID','interface socket identity already exists',loc)
        seen.add(r['id']);kind=r.get('kind');native,_,spec=kind_descriptor(kind,family)
        d=validate_arguments({'description':{**text(),'maxLength':1024}},{'description':r.get('description','')},location=loc)
        d.update(id=r['id'],kind=kind)
        if spec is None:
            if any(k in r for k in ('default','minimum','maximum')):fail('UNSUPPORTED_OPTION','this socket carries links and has no authored literal default',loc)
        else:
            if kind in ('number','integer'):
                bounds=validate_arguments({'minimum':number(-1000000,minimum=-1e30,maximum=1e30),'maximum':number(1000000,minimum=-1e30,maximum=1e30)},{k:v for k,v in r.items() if k in ('minimum','maximum')},location=loc)
                if bounds['minimum']>bounds['maximum'] or kind=='integer' and any(type(v) is not int or abs(v)>1000000 for v in bounds.values()):fail('INVALID_ARGUMENT','numeric interface bounds are invalid',loc)
                d.update(bounds);spec={**spec,**bounds}
            elif any(k in r for k in ('minimum','maximum')):fail('UNSUPPORTED_OPTION','bounds apply only to numeric interface sockets',loc)
            d['default']=validate_arguments({'value':spec},{'value':r.get('default',spec['default'])},location=loc)['value']
        result.append(d)
    return result


def validate_groups(value,where):
    if not isinstance(value,list) or len(value)>128:fail('INVALID_NODE_GRAPH','nodeGroups must be a bounded array',where)
    groups={};raw={}
    from schemaxis.pipeline import name
    for i,g in enumerate(value):
        loc=f'{where}[{i}]';keys(g,('id','family','inputs','outputs','nodes','links'),loc);name(g.get('id'),loc+'.id')
        if g['id'] in groups:fail('DUPLICATE_ID','node group identity already exists',loc)
        family=g.get('family')
        if not isinstance(family,str) or family not in DOMAINS:fail('TYPE_MISMATCH','node group requires a reviewed node domain',loc)
        groups[g['id']]={'id':g['id'],'family':family,'inputs':_interface(g.get('inputs'),family,loc+'.inputs'),'outputs':_interface(g.get('outputs'),family,loc+'.outputs',True)};raw[g['id']]=g
    dependencies={}
    for identity,g in raw.items():
        if not isinstance(g.get('nodes'),list):fail('INVALID_NODE_GRAPH','group nodes must be an array',where)
        dependencies[identity]=set()
        for n in g['nodes']:
            if isinstance(n,dict) and n.get('kind')=='group':
                name(n.get('group'),where+'.'+identity+'.group');dependencies[identity].add(n['group'])
        if not dependencies[identity]<=set(groups):fail('UNKNOWN_REFERENCE','nested node group reference is absent',identity)
    pending=set(groups);ordered=[]
    while pending:
        ready=sorted(n for n in pending if not dependencies[n]&pending)
        if not ready:fail('DEPENDENCY_CYCLE','node groups contain a recursive dependency',where)
        ordered.extend(ready);pending.difference_update(ready)
    from .node_catalogue import validate_graph
    for identity in ordered:
        g=groups[identity];authored=raw[identity]
        graph=validate_graph({k:authored[k] for k in ('id','nodes','links')},g['family'],where+'.'+identity,groups=groups,interface=g)
        groups[identity]={**g,'nodes':graph['nodes'],'links':graph['links']}
    return [groups[n] for n in ordered]


def references(graph,family,groups,interface=None):
    result=[]
    for n in graph['nodes']:
        desc=descriptor(n,family,groups,interface)
        for key,value in n['values'].items():
            kind=desc['inputs'][key]['kind']
            if kind in REFERENCE_KINDS and not (kind=='image' and family=='compositor') and value:result.append((kind,value))
    return result
