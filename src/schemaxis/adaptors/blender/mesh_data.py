"""Typed mesh fields and texture-coordinate intent, independent of native imports."""
import copy
import math
import struct
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from schemaxis.schema import arguments_schema, object_schema
from .node_catalogue import number, integer, boolean, choice, text, vector, colour

NAME={'type':'string','minLength':1,'maxLength':63}
def array(item,limit=100000,minimum=0):return {'type':'array','items':item,'minItems':minimum,'maxItems':limit}
def record(props,required=()):return {'type':'object','properties':{k:{**{a:b for a,b in v.items() if a!='default' or k not in required},**({'required':True} if k in required else {})} for k,v in props.items()}}
def tuple_(n,item=None):return {'type':'array','items':item or {'type':'number'},'minItems':n,'maxItems':n}
# Native type, trusted data member, authored value, semantic node socket kind.
CHANNELS={
 'float':('FLOAT','value',number(),'number'),
 'integer':('INT','value',integer(0,minimum=-2147483648,maximum=2147483647),'integer'),
 'boolean':('BOOLEAN','value',boolean(),'boolean'),
 'vector':('FLOAT_VECTOR','vector',vector(),'vector'),
 'colour':('FLOAT_COLOR','color',colour(),'colour'),
 'byteColour':('BYTE_COLOR','color_srgb',tuple_(4,{'type':'integer','minimum':0,'maximum':255}),'colour'),
 'vector2':('FLOAT2','vector',tuple_(2),'vector2'),
 'quaternion':('QUATERNION','value',tuple_(4),'rotation'),
}
DOMAINS=['POINT','EDGE','FACE','CORNER']
EDGE=tuple_(2,{'type':'integer','minimum':0})
COMMON={'object':{**NAME,'required':True},'sourceObject':text(),
 'sharing':choice('refuse',['refuse','copy','shared']),'activeUV':text(),'renderUV':text(),
 'activeColour':text(),'renderColour':text()}
UV_COMMON={'name':{**NAME,'required':True},'pack':boolean(),
 'textureSize':tuple_(2,{'type':'integer','minimum':1,'maximum':32768}),
 'paddingPixels':integer(4,minimum=0,maximum=1024),'rotate':boolean(True)}
UV_COMMON['textureSize']['default']=[1024,1024]
UV_TRANSFORM=record({'offset':{**tuple_(2),'default':[0,0]},
    'pivot':{**tuple_(2),'default':[0,0]},
    'scale':{**tuple_(2),'default':[1,1]},
    'rotationDegrees':number(0,minimum=-360000,maximum=360000)})
# Optional: preserve the normalized shape of historical coordinate contracts.
UV_COMMON['transform']=UV_TRANSFORM
UV_METHODS={
 'coordinates':{'coordinates':{**array(array(tuple_(2),1024,3),100000,1),'required':True}},
 'planar':{'axis':choice('Z',['X','Y','Z']),'origin':vector(),'size':{**tuple_(2,{'type':'number','minimum':1e-12}),'default':[1,1]}},
 'box':{'origin':vector(),'size':{**vector((1,1,1))}},
 'smart':{'angle':number(math.radians(66),minimum=.001,maximum=math.pi/2),'areaWeight':number(0,minimum=0,maximum=1)},
 'unwrap':{'unwrapMethod':choice('CONFORMAL',['CONFORMAL','ANGLE_BASED','MINIMUM_STRETCH']),'seams':array(EDGE,100000),'fillHoles':boolean(True),'iterations':integer(10,minimum=1,maximum=1000)},
 'copy':{'source':{**NAME,'required':True}},
}


def field_declaration(kind,mode):
    value={k:v for k,v in CHANNELS[kind][2].items() if k!='default'}
    p={'name':{**NAME,'required':True},'domain':choice('POINT',DOMAINS)}
    if mode=='constant':p['value']={**value,'required':True}
    elif mode=='dense':p['values']={**array(value,100000,1),'required':True}
    else:
        p['default']={**value,'required':True}
        p['entries']={**array(record({'index':{'type':'integer','minimum':0},'value':value},['index','value']),100000,1),'required':True}
    return p


def schema_property():
    fields=[]
    for kind in CHANNELS:
        for mode in ('constant','dense','sparse'):
            s=arguments_schema(field_declaration(kind,mode));s['properties'].update(kind={'const':kind},mode={'const':mode});s['required']+=['kind','mode'];fields.append(s)
    maps=[]
    for method,props in UV_METHODS.items():
        s=arguments_schema({**UV_COMMON,**props});s['properties']['method']={'const':method};s['required'].append('method');maps.append(s)
    p=arguments_schema(COMMON);p['properties'].update(attributes=array({'oneOf':fields},128),uvMaps=array({'oneOf':maps},8))
    return array(p,1024)


def _name(value,where):
    if not isinstance(value,str) or not value or len(value.encode())>63 or value.startswith('.') or value in ('position','id','material_index','sharp_edge','sharp_face','uv_seam'):
        fail('INVALID_MESH_DATA','use a non-reserved mesh channel name of at most 63 UTF-8 bytes',where)


def validate(authored,result,kinds,where):
    authored=authored.get('meshData',[]);where+='.meshData'
    if not isinstance(authored,list) or len(authored)>1024:fail('INVALID_MESH_DATA','meshData must be a bounded array',where)
    out=[];seen=set()
    for i,item in enumerate(authored):
        loc=f'{where}[{i}]';keys(item,(*COMMON,'attributes','uvMaps'),loc)
        r=validate_arguments(COMMON,{k:v for k,v in item.items() if k in COMMON},location=loc)
        if kinds.get(r['object']) not in ('mesh','instance','asset'):fail('TYPE_MISMATCH','mesh data requires a mesh or imported asset root',loc)
        if r['sourceObject'] and kinds[r['object']]!='asset':fail('INVALID_MESH_DATA','sourceObject selects a member of an imported asset',loc)
        target=(r['object'],r['sourceObject'])
        if target in seen:fail('INVALID_MESH_DATA','combine channels for one target in a single declaration',loc)
        seen.add(target);r['attributes']=[];r['uvMaps']=[];names=set()
        for field,limit in [('attributes',128),('uvMaps',8)]:
            if not isinstance(item.get(field,[]),list) or len(item.get(field,[]))>limit:fail('INVALID_MESH_DATA','channel collection exceeds limit',loc+'.'+field)
            for j,c in enumerate(item.get(field,[])):
                here=f'{loc}.{field}[{j}]'
                if not isinstance(c,dict):fail('INVALID_MESH_DATA','channel must be an object',here)
                _name(c.get('name'),here)
                if c['name'] in names:fail('DUPLICATE_ID','channel names must be distinct across attributes and UV maps',here)
                names.add(c['name'])
                if field=='attributes':
                    kind=c.get('kind');mode=c.get('mode')
                    if kind not in CHANNELS or mode not in ('constant','dense','sparse'):fail('INVALID_MESH_DATA','choose a typed channel and constant/dense/sparse storage',here)
                    d=validate_arguments(field_declaration(kind,mode),{k:v for k,v in c.items() if k not in ('kind','mode')},location=here)
                    if kind=='vector2' and d['domain']=='CORNER':fail('INVALID_MESH_DATA','CORNER vector2 is a texture-coordinate map; declare uvMaps',here)
                    if mode=='sparse' and len({e['index'] for e in d['entries']})!=len(d['entries']):fail('INVALID_MESH_DATA','sparse indices must be unique',here)
                    vals=[d['value']] if mode=='constant' else d['values'] if mode=='dense' else [d['default'],*(e['value'] for e in d['entries'])]
                    if kind=='quaternion' and any(abs(sum(x*x for x in q)-1)>1e-5 for q in vals):fail('INVALID_MESH_DATA','quaternions use normalized (w,x,y,z) rotation storage',here)
                    r[field].append({'kind':kind,'mode':mode,**d})
                else:
                    method=c.get('method')
                    if method not in UV_METHODS:fail('INVALID_MESH_DATA','choose coordinates, copy, planar, box, smart or unwrap mapping',here)
                    d=validate_arguments({**UV_COMMON,**UV_METHODS[method]},{k:v for k,v in c.items() if k!='method'},location=here)
                    if method=='copy':
                        if d['source']==d['name']:fail('INVALID_MESH_DATA','a UV copy needs a distinct source set',here+'.source')
                        later={v.get('name') for v in item.get('uvMaps',[])[j:] if isinstance(v,dict)}
                        if d['source'] in later:fail('INVALID_MESH_DATA','copy from an original set or an earlier declared set; forward UV references are ambiguous',here+'.source')
                    if 'transform' in d:
                        if any(x==0 for x in d['transform']['scale']):fail('INVALID_MESH_DATA','UV scale must be nonzero; negative components explicitly mirror the stored basis',here+'.transform.scale')
                        if d['pack']:fail('INVALID_MESH_DATA','transform a separate copy of a packed set so padding and unit-tile guarantees remain explicit',here+'.transform')
                    if method=='unwrap' and d['unwrapMethod']!='MINIMUM_STRETCH' and d['iterations']!=10:fail('INVALID_MESH_DATA','iterations applies only to minimum-stretch unwrap',here)
                    if method=='box' and min(d['size'])<=0:fail('INVALID_MESH_DATA','box mapping size must be positive',here)
                    if not d['pack'] and any(k in c for k in ('textureSize','paddingPixels','rotate')):
                        # Normalized documents include these defaults on revalidation.
                        if any(d[k]!=UV_COMMON[k]['default'] for k in ('textureSize','paddingPixels','rotate')):fail('INVALID_MESH_DATA','packing controls require pack=true',here)
                    if d['paddingPixels']*2>=min(d['textureSize']):fail('INVALID_MESH_DATA','padding leaves no texture area',here)
                    if method=='unwrap':
                        d.setdefault('seams',[])
                        if any(a==b for a,b in d['seams']) or len({tuple(sorted(e)) for e in d['seams']})!=len(d['seams']):fail('INVALID_MESH_DATA','seams need distinct unique endpoint pairs',here)
                    r[field].append({'method':method,**d})
        for key in ('activeUV','renderUV'):
            if r[key] and r[key] not in {u['name'] for u in r['uvMaps']}:fail('UNKNOWN_REFERENCE','active/render UV must name a declared coordinate set',loc+'.'+key)
        for key in ('activeColour','renderColour'):
            if r[key] and r[key] not in {a['name'] for a in r['attributes'] if a['kind'] in ('colour','byteColour')}:
                fail('UNKNOWN_REFERENCE','active/render colour must name a declared colour channel',loc+'.'+key)
        if not r['attributes'] and not r['uvMaps']:fail('INVALID_MESH_DATA','mesh data needs at least one channel',loc)
        owned=next((o for o in result['objects'] if o['id']==r['object'] and o['kind']=='mesh'),None)
        unwraps=[u for u in r['uvMaps'] if u['method']=='unwrap']
        if unwraps and any({tuple(sorted(e)) for e in u['seams']}!={tuple(sorted(e)) for e in unwraps[0]['seams']} for u in unwraps):fail('INVALID_MESH_DATA','seam edges are shared by all coordinate sets on a Mesh',loc)
        if owned:
            if owned.get('uv') and any(u['name']=='UVMap' for u in r['uvMaps']):fail('INVALID_MESH_DATA','legacy mesh uv already owns UVMap; omit uv or use a distinct named set',loc)
            validate_topology(r,owned['vertices'],owned['faces'],loc)
        out.append(r)
    return out


def edges_for(faces):return sorted({tuple(sorted((a,b))) for f in faces for a,b in zip(f,f[1:]+f[:1])})


def values_for(channel,count,where='meshData'):
    if channel['mode']=='dense':
        if len(channel['values'])!=count:fail('INVALID_MESH_DATA','dense values must match the selected mesh domain',where,expected=count)
        return channel['values']
    result=[copy.deepcopy(channel['value'] if channel['mode']=='constant' else channel['default']) for _ in range(count)]
    if channel['mode']=='sparse':
        for e in channel['entries']:
            if e['index']>=count:fail('INVALID_MESH_DATA','sparse index outside selected mesh domain',where)
            result[e['index']]=e['value']
    return result


def validate_topology(spec,vertices,faces,where='meshData',edges=None):
    face_edges=edges_for(faces)
    if edges is None:edges=list(face_edges)
    if not isinstance(edges,list) or len(edges)>100000:fail('RESOURCE_BUDGET_EXCEEDED','mesh edge topology exceeds bounded domain budget',where)
    if any(not isinstance(e,(list,tuple)) or len(e)!=2 or any(type(i) is not int or not 0<=i<len(vertices) for i in e) or e[0]==e[1] for e in edges):fail('INVALID_MESH_DATA','mesh edges require distinct valid endpoint indices',where)
    edges=[tuple(sorted(e)) for e in edges]
    if len(set(edges))!=len(edges) or not set(face_edges)<=set(edges):fail('INVALID_MESH_DATA','mesh edge topology is duplicated or omits polygon boundaries',where)
    edges=sorted(edges);sizes={'POINT':len(vertices),'EDGE':len(edges),'FACE':len(faces),'CORNER':sum(map(len,faces))}
    if max(sizes.values())>100000 or sum(sizes[a['domain']] for a in spec['attributes'])>1000000:fail('RESOURCE_BUDGET_EXCEEDED','mesh channels exceed bounded domain/value budget',where)
    for a in spec['attributes']:values_for(a,sizes[a['domain']],where+'.'+a['name'])
    for uv in spec['uvMaps']:
        if uv['method']=='coordinates' and (len(uv['coordinates'])!=len(faces) or any(len(c)!=len(f) for c,f in zip(uv['coordinates'],faces))):fail('INVALID_MESH_DATA','UV coordinates must match all face corners',where)
        if uv['method']=='unwrap' and any(tuple(sorted(e)) not in set(edges) for e in uv['seams']):fail('INVALID_MESH_DATA','seam endpoint pair is not a mesh edge',where)
    return sizes


def projection(uv,vertices,faces):
    """Original mesh-local coordinates; parent/asset transforms are excluded."""
    result=[]
    for face in faces:
        axis=uv.get('axis')
        if uv['method']=='box':
            points=[vertices[i] for i in face]
            normal=[sum((p[(i+1)%3]-q[(i+1)%3])*(p[(i+2)%3]+q[(i+2)%3]) for p,q in zip(points,points[1:]+points[:1])) for i in range(3)]
            if not any(normal):fail('INVALID_MESH_DATA','box projection needs non-degenerate polygon normals')
            axis='XYZ'[max(range(3),key=lambda i:abs(normal[i]))]
        indices={'X':(1,2),'Y':(0,2),'Z':(0,1)}[axis];size=uv['size'] if uv['method']=='planar' else [uv['size'][i] for i in indices]
        result.append([[(vertices[v][i]-uv['origin'][i])/size[j] for j,i in enumerate(indices)] for v in face])
    return result


def transform_uv(coordinates,intent):
    """Scale about pivot, rotate counterclockwise, then translate stored UVs."""
    if intent is None:return coordinates
    angle=math.radians(intent['rotationDegrees']);c=math.cos(angle);s=math.sin(angle)
    px,py=intent['pivot'];sx,sy=intent['scale'];dx,dy=intent['offset']
    result=[]
    for face in coordinates:
        points=[]
        for u,v in face:
            x,y=(u-px)*sx,(v-py)*sy
            point=[px+c*x-s*y+dx,py+s*x+c*y+dy]
            if any(not math.isfinite(a) for a in point):fail('INVALID_MESH_DATA','UV transform exceeds finite coordinates')
            points.append(point)
        result.append(points)
    # Native UV storage is float32. An invertible authored transform must not
    # silently merge distinct adjacent corners or destroy/reverse a source
    # triangle's orientation after translation and storage rounding. This is a
    # local feature check, independent of the overall atlas span or offset.
    for source,transformed in zip(coordinates,result):
        try:stored=[[struct.unpack('f',struct.pack('f',v))[0] for v in p] for p in transformed]
        except (OverflowError,struct.error):
            fail('NATIVE_VALUE_MISMATCH','UV transform exceeds finite native storage; recenter or rescale the stored map')
        if any(not math.isfinite(v) for p in stored for v in p):
            fail('NATIVE_VALUE_MISMATCH','UV transform exceeds finite native storage; recenter or rescale the stored map')
        for i,p in enumerate(source):
            j=(i+1)%len(source)
            if p!=source[j] and stored[i]==stored[j]:
                fail('NATIVE_VALUE_MISMATCH','UV transform collapses distinct adjacent corners in native storage; reduce offset or rescale the map')
        def area(points,i):
            a,b,c=points[0],points[i],points[i+1]
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        mirrored=(sx<0)!=(sy<0)
        for i in range(1,len(source)-1):
            before=area(source,i);after=area(stored,i)
            if before and (not after or ((after<0)!=(before<0))!=mirrored):
                fail('NATIVE_VALUE_MISMATCH','UV transform loses the stored orientation of a source triangle; reduce offset or rescale the map')
    return result


def verify(spec,actual):
    from .settings import matching
    if not isinstance(actual,list) or len(actual)!=len(spec):fail('VERIFICATION_FAILED','mesh data readback membership differs')
    for s,a in zip(spec,actual):
        if (s['object'],s['sourceObject'],s['sharing'])!=(a.get('object'),a.get('sourceObject'),a.get('sharing')):fail('VERIFICATION_FAILED','mesh data target differs')
        vertices=a['vertices'];faces=a['faces'];sizes=validate_topology(s,vertices,faces,edges=a.get('edges'))
        expected=[{'name':c['name'],'kind':c['kind'],'domain':c['domain'],'values':values_for(c,sizes[c['domain']])} for c in s['attributes']]
        if not matching(a['attributes'],expected):fail('VERIFICATION_FAILED','mesh channel values differ from authored fields')
        if len(a['uvMaps'])!=len(s['uvMaps']):fail('VERIFICATION_FAILED','UV membership differs')
        for u,v in zip(s['uvMaps'],a['uvMaps']):
            if u['name']!=v['name']:fail('VERIFICATION_FAILED','UV name differs')
            coords=v['coordinates']
            if len(coords)!=len(faces) or any(len(c)!=len(f) for c,f in zip(coords,faces)) or any(not math.isfinite(x) for f in coords for p in f for x in p):fail('VERIFICATION_FAILED','UV topology or finite coordinates differ')
            expected=u['coordinates'] if u['method']=='coordinates' else projection(u,vertices,faces) if u['method'] in ('planar','box') else None
            if expected is not None:expected=transform_uv(expected,u.get('transform'))
            if expected is not None and not u['pack'] and not matching(coords,expected):fail('VERIFICATION_FAILED','UV coordinates differ from requested mapping')
            if u['pack'] and any(x < -1e-6 or x > 1+1e-6 for f in coords for p in f for x in p):fail('VERIFICATION_FAILED','packed UV coordinates leave the unit tile')
            if u['method']=='unwrap' and sorted(v['seams'])!=sorted([list(e) for e in sorted(tuple(sorted(e)) for e in u['seams'])]):fail('VERIFICATION_FAILED','UV unwrap seam edges differ')
        for k in ('activeUV','renderUV'):
            expected=s[k] or (s['uvMaps'][0]['name'] if s['uvMaps'] else '')
            if expected and a[k]!=expected:fail('VERIFICATION_FAILED','active/render texture coordinate selection differs')
        colours=[c['name'] for c in s['attributes'] if c['kind'] in ('colour','byteColour')]
        for k in ('activeColour','renderColour'):
            expected=s[k] or (colours[0] if colours else '')
            if expected and a[k]!=expected:fail('VERIFICATION_FAILED','active/render colour selection differs')
