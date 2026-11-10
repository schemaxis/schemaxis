"""Named surface layouts and independent Object palettes, without native imports."""
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from schemaxis.schema import arguments_schema
from .mesh_data import NAME,array,record
from .node_catalogue import choice,text,integer,vector,number,boolean
from .spline import union,variant

SLOT=record({'id':NAME,'material':NAME},['id','material'])
SELECTORS={
 'all':{},
 'faceIndices':{'indices':{**array({'type':'integer','minimum':0},100000,1),'required':True}},
 'faceBox':{'minimum':{**vector(),'required':True},'maximum':{**vector(),'required':True},'test':choice('center',['center','contained']),'invert':boolean()},
 'faceNormal':{'direction':vector((0,0,1)),'angle':number(0,minimum=0,maximum=3.141592653589793),'invert':boolean()},
 'splines':{'names':{**array(NAME,128,1),'required':True}},
 'splineIndices':{'indices':{**array({'type':'integer','minimum':0},4096,1),'required':True}},
 'characters':{'start':integer(0,minimum=0,required=True),'end':integer(1,minimum=1,required=True)},
}
SELECTION=union([variant(k,v) for k,v in SELECTORS.items()])
COMMON={'id':{**NAME,'required':True},'object':{**NAME,'required':True},'sourceObject':text()}
LAYOUT={'sharing':choice('refuse',['refuse','copy','shared']),
 'slots':{**array(SLOT,256,1),'required':True},'defaultSlot':{**NAME,'required':True},
 'regions':array(record({'slot':NAME,'selection':SELECTION},['slot','selection']),256)}
OVERRIDE={'layout':{**NAME,'required':True},'slots':{**array(SLOT,256,1),'required':True}}


def schema_property():
    variants=[]
    for kind,options in [('layout',LAYOUT),('override',OVERRIDE)]:
        s=arguments_schema({**COMMON,**options});s['properties']['kind']={'const':kind};s['required'].append('kind');variants.append(s)
    return array({'oneOf':variants},256)


def validate(value,kinds,materials,objects,where='production.materialAssignments'):
    if not isinstance(value,list) or len(value)>256:fail('INVALID_MATERIAL_ASSIGNMENT','provide at most256 material assignment records',where)
    result=[];ids=set();targets=set()
    for i,item in enumerate(value):
        loc=f'{where}[{i}]';kind=item.get('kind') if isinstance(item,dict) else None
        if kind not in ('layout','override'):fail('INVALID_MATERIAL_ASSIGNMENT','choose a DATA layout or OBJECT palette override',loc)
        r=validate_arguments({**COMMON,**(LAYOUT if kind=='layout' else OVERRIDE)},{k:v for k,v in item.items() if k!='kind'},location=loc)
        if r['id'] in ids:fail('DUPLICATE_ID','material assignment IDs must be distinct',loc)
        ids.add(r['id']);identity=(r['object'],r['sourceObject'])
        if identity in targets:fail('INVALID_MATERIAL_ASSIGNMENT','combine one target in one layout or override',loc)
        targets.add(identity)
        if kinds.get(r['object']) not in ('mesh','curve','spline','text','instance','asset'):fail('TYPE_MISMATCH','material assignment needs Mesh, classic Curve, text or a captured geometric part',loc)
        if r['sourceObject'] and kinds[r['object']]!='asset':fail('INVALID_MATERIAL_ASSIGNMENT','sourceObject selects a captured native/glTF part',loc)
        slots=[s['id'] for s in r['slots']]
        if len(set(slots))!=len(slots):fail('DUPLICATE_ID','logical material slot IDs must be distinct',loc+'.slots')
        if any(s['material'] not in materials for s in r['slots']):fail('UNKNOWN_REFERENCE','slot must reference a declared material',loc+'.slots')
        if kind=='layout':
            r.setdefault('regions',[])
            if r['defaultSlot'] not in slots or any(a['slot'] not in slots for a in r['regions']):fail('UNKNOWN_REFERENCE','default and region slots must belong to this layout',loc)
            for region in r['regions']:
                s=region['selection'];sk=s['kind']
                sequence=s.get('indices',s.get('names',[]))
                if len(set(sequence))!=len(sequence):fail('INVALID_MATERIAL_ASSIGNMENT','selection identities must be distinct',loc)
                if sk=='characters' and s['start']>=s['end']:fail('INVALID_MATERIAL_ASSIGNMENT','character range is nonempty and half-open',loc)
                if sk=='faceBox' and any(a>b for a,b in zip(s['minimum'],s['maximum'])):fail('INVALID_MATERIAL_ASSIGNMENT','box minimum must not exceed maximum',loc)
                if sk=='faceNormal' and not any(s['direction']):fail('INVALID_MATERIAL_ASSIGNMENT','normal direction must be nonzero',loc)
        result.append({'kind':kind,**r})
    layouts={r['id']:r for r in result if r['kind']=='layout'}
    work=0
    for r in result:
        if r['kind']=='override':
            source=layouts.get(r['layout'])
            if source is None:fail('UNKNOWN_REFERENCE','override must reference a named DATA layout',where)
            if {s['id'] for s in source['slots']}!={s['id'] for s in r['slots']}:fail('INVALID_MATERIAL_ASSIGNMENT','override must map every logical layout slot exactly once',where)
        else:
            by_id={o['id']:o for o in objects};owned=by_id.get(r['object']);seen=set()
            while owned and owned['kind']=='instance' and owned['id'] not in seen:
                seen.add(owned['id']);owned=by_id.get(owned['source'])
            if owned:
                if owned['kind']=='mesh':
                    from .mesh_edits import mesh
                    work+=selection_work(r,len(owned['faces']))
                    if work>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate material selection work exceeds one million elements',where)
                    indices(r,'FACE',len(owned['faces']),mesh(owned['vertices'],owned['faces']))
                elif owned['kind'] in ('curve','spline'):
                    names=[s['id'] for s in owned['splines']] if owned['kind']=='spline' else []
                    work+=selection_work(r,len(names) if names else 1)
                    if work>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate material selection work exceeds one million elements',where)
                    indices(r,'SPLINE',len(names) if names else 1,spline_names=names)
                elif owned['kind']=='text':
                    work+=selection_work(r,len(owned['body']))
                    if work>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate material selection work exceeds one million elements',where)
                    indices(r,'CHARACTER',len(owned['body']))
    return result


def selection_work(layout,count):
    """Charge full-domain scans before geometry allocation or selector execution."""
    work=count
    for region in layout['regions']:
        s=region['selection'];kind=s['kind']
        if kind in ('all','faceBox','faceNormal'):work+=count
        elif kind=='splines':work+=count*len(s['names'])
        elif kind=='characters':work+=min(count,max(0,s['end']-s['start']))
        else:work+=len(s['indices'])
    if work>1000000:fail('RESOURCE_BUDGET_EXCEEDED','material selection work exceeds one million elements; reduce full-domain regions or use explicit indices',layout['id'])
    return work


def indices(layout,domain,count,geometry=None,spline_names=()):
    """Resolve disjoint current-stage regions; no native slot numbers are input."""
    if not 0<count<=100000:fail('RESOURCE_BUDGET_EXCEEDED','material assignment requires1–100000 surface elements',layout['id'])
    selection_work(layout,count)
    slots={s['id']:i for i,s in enumerate(layout['slots'])};out=[slots[layout['defaultSlot']]]*count;used=set()
    for region in layout['regions']:
        s=region['selection'];kind=s['kind']
        if kind=='all':selected=set(range(count))
        elif kind in ('faceIndices','faceBox','faceNormal'):
            if domain!='FACE':fail('TYPE_MISMATCH','face selection requires Mesh data',layout['id'])
            if kind=='faceIndices':selected=set(s['indices'])
            else:
                from .mesh_edits import select
                sk='box' if kind=='faceBox' else 'normal'
                selected=set(select(geometry,{'kind':sk,'domain':'FACE',**{k:v for k,v in s.items() if k!='kind'}}))
        elif kind in ('splines','splineIndices'):
            if domain!='SPLINE':fail('TYPE_MISMATCH','spline selection requires classic Curve data',layout['id'])
            if kind=='splines':
                if not spline_names or any(n not in spline_names for n in s['names']):fail('UNKNOWN_REFERENCE','named spline selection requires authored spline identities; imported controls use explicit splineIndices',layout['id'])
                selected={spline_names.index(n) for n in s['names']}
            else:selected=set(s['indices'])
        else:
            if domain!='CHARACTER':fail('TYPE_MISMATCH','character selection requires text data',layout['id'])
            selected=set(range(s['start'],s['end'])) if s['end']<=count else {count}
        if not selected or min(selected)<0 or max(selected)>=count:fail('INVALID_MATERIAL_ASSIGNMENT','material region must select existing nonempty surface elements',layout['id'])
        if used&selected:fail('INVALID_MATERIAL_ASSIGNMENT','material regions overlap; combine or partition the selections explicitly',layout['id'])
        used|=selected
        for index in selected:out[index]=slots[region['slot']]
    return out


def verify(spec,records):
    if not isinstance(records,list) or len(records)!=len(spec):fail('VERIFICATION_FAILED','material assignment membership differs')
    layouts={s['id']:s for s in spec if s['kind']=='layout'}
    for s,r in zip(spec,records):
        if not isinstance(r,dict) or r.get('id')!=s['id'] or r.get('kind')!=s['kind'] or r.get('object')!=s['object'] or r.get('sourceObject')!=s['sourceObject']:fail('VERIFICATION_FAILED','material assignment target identity differs')
        if r.get('domain') not in ('FACE','SPLINE','CHARACTER') or not isinstance(r.get('owners'),list) or not r['owners'] or r['owners']!=sorted(set(r['owners'])) or r.get('nativeObject') not in r['owners']:fail('VERIFICATION_FAILED','material assignment data ownership differs')
        values=r.get('indices');slots=r.get('slots')
        source=s if s['kind']=='layout' else layouts[s['layout']]
        palette={slot['id']:slot for slot in s['slots']}
        expected_slots=[palette[slot['id']] for slot in source['slots']]
        if slots!=expected_slots or r.get('logicalSlots')!=[v['id'] for v in expected_slots] or len(slots)!=len(s['slots']):fail('VERIFICATION_FAILED','logical material palette differs')
        if not isinstance(values,list) or not 0<len(values)<=100000 or any(type(v) is not int or not 0<=v<len(slots) for v in values):fail('VERIFICATION_FAILED','surface material indices differ')
        expected_link='DATA' if s['kind']=='layout' else 'OBJECT'
        # A layout's own Object remains DATA-linked; overrides are distinct targets.
        if r.get('links')!=[expected_link]*len(slots):fail('VERIFICATION_FAILED','material slot ownership differs')
        if r.get('dataMaterials')!=[slot['material'] for slot in source['slots']]:fail('VERIFICATION_FAILED','underlying DATA palette differs')
