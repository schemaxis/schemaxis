"""Native classic Curve construction and complete control-geometry readback."""
import math
import bpy
from schemaxis.errors import fail
from .spline import fill_mode

FIELDS={'dimensions':'dimensions','fillRule':'fill_rule','fillSolver':'fill_solver','offset':'offset','extrude':'extrude',
 'caps':'use_fill_caps','twist':'twist_mode','twistSmooth':'twist_smooth'}
SAMPLING={'preview':'resolution_u','render':'render_resolution_u'}
TRIM={'start':'bevel_factor_start','end':'bevel_factor_end','startMapping':'bevel_factor_mapping_start','endMapping':'bevel_factor_mapping_end'}
PATH={'enabled':'use_path','duration':'path_duration','follow':'use_path_follow','radius':'use_radius','stretch':'use_stretch','bounds':'use_deform_bounds'}
SPLINE={'closed':'use_cyclic_u','smooth':'use_smooth','sampling':'resolution_u','radiusInterpolation':'radius_interpolation','tiltInterpolation':'tilt_interpolation'}


def _edge_precision(p,q,a,b,identity):
    delta=[y-x for x,y in zip(p,q)];actual=[y-x for x,y in zip(a,b)]
    scale=max(abs(x) for x in delta)
    if any(abs(x-y)>scale*1e-6 for x,y in zip(delta,actual)):
        fail('NATIVE_VALUE_MISMATCH','Curve segment or handle loses local precision; recenter or rescale the controls',identity)


def _precision(authored,actual,identity,closed=False):
    span=max(max(p[i] for p in authored)-min(p[i] for p in authored) for i in range(3))
    if not span or any(not math.isclose(a,b,rel_tol=0,abs_tol=span*1e-6) for p,q in zip(authored,actual) for a,b in zip(p,q)):
        fail('NATIVE_VALUE_MISMATCH','Curve control geometry loses local precision; recenter or rescale the controls',identity)
    pairs=list(zip(range(len(authored)-1),range(1,len(authored))))
    if closed:pairs.append((len(authored)-1,0))
    for i,j in pairs:_edge_precision(authored[i],authored[j],actual[i],actual[j],identity)


def create(o,materials=None):
    data=bpy.data.curves.new(o['id'],'CURVE')
    for key,prop in FIELDS.items():
        setattr(data,prop,o[key])
        if not _same(getattr(data,prop),o[key]):fail('NATIVE_VALUE_MISMATCH','native Curve setting changed the authored value',o['id'],field=key)
    data.fill_mode=fill_mode(o)
    for values,mapping in ((o['sampling'],SAMPLING),(o['trim'],TRIM),(o['path'],PATH)):
        for key,prop in mapping.items():
            setattr(data,prop,values[key])
            if not _same(getattr(data,prop),values[key]):fail('NATIVE_VALUE_MISMATCH','native sampling, trim or path value changed authored intent',o['id'],field=key)
    bevel=o['bevel'];data.bevel_mode={'none':'ROUND','round':'ROUND','object':'OBJECT','profile':'PROFILE'}[bevel['kind']]
    data.bevel_depth=bevel.get('depth',0);data.bevel_resolution=bevel.get('resolution',0)
    if not _same(data.bevel_depth,bevel.get('depth',0)):fail('NATIVE_VALUE_MISMATCH','native bevel depth lost authored precision',o['id'])
    if bevel['kind']=='profile':
        profile=data.bevel_profile;profile.use_clip=True
        for p in bevel['points'][1:-1]:profile.points.add(*p['position'])
        if len(profile.points)!=len(bevel['points']):fail('NATIVE_VALUE_MISMATCH','native quarter-profile control count differs',o['id'])
        # Point insertion chooses a nearby segment. Assign the complete ordered
        # path afterwards, then select one point for its public handle setter.
        for n,p in zip(profile.points,bevel['points']):n.location=p['position']
        for n,p in zip(profile.points,bevel['points']):
            for other in profile.points:other.select=False
            n.select=True;n.handle_type_1=p['handle'];n.handle_type_2=p['handle'];n.select=False
        profile.use_sample_even_lengths=bevel['evenLengths'];profile.use_sample_straight_edges=bevel['straightEdges'];profile.update()
        if len(profile.points)!=len(bevel['points']) or any(not _same(list(n.location),p['position']) or n.handle_type_1!=p['handle'] or n.handle_type_2!=p['handle'] for n,p in zip(profile.points,bevel['points'])):fail('NATIVE_VALUE_MISMATCH','native profile controls or handle policy changed; separate nearby controls',o['id'])
    for authored_spline in o['splines']:
        authored=[];written=[]
        s=dict(authored_spline)
        if s['reverse']:
            s['points']=[{**p,**({'left':p['right'],'right':p['left']} if s['kind']=='BEZIER' else {})} for p in reversed(s['points'])]
        native=data.splines.new(s['kind']);points=native.bezier_points if s['kind']=='BEZIER' else native.points;points.add(len(s['points'])-1)
        for p,n in zip(s['points'],points):
            n.co=p['position'] if s['kind']=='BEZIER' else (*p['position'],p.get('weight',1))
            n.radius=p['radius'];n.tilt=p['tilt']
            if not _same(n.radius,p['radius']) or not _same(n.tilt,p['tilt']) or s['kind']=='NURBS' and not _same(n.co[3],p['weight']):fail('NATIVE_VALUE_MISMATCH','native radius, tilt or rational weight lost authored precision',o['id'])
            authored.append(p['position']);written.append(list(n.co)[:3])
            if s['kind']=='BEZIER':
                n.handle_left_type='FREE';n.handle_right_type='FREE'
                for side in ('left','right'):
                    h=p[side]
                    if 'position' in h:
                        setattr(n,'handle_'+side,h['position']);authored.append(h['position']);written.append(list(getattr(n,'handle_'+side)))
        for key,prop in SPLINE.items():setattr(native,prop,(s.get(key,0) or o['sampling']['preview']) if key=='sampling' else s.get(key,'LINEAR'))
        if s['kind']=='NURBS':native.order_u=s['order'];native.use_endpoint_u=s['endpoint'];native.use_bezier_u=s['bezierKnots']
        if s['kind']=='BEZIER':
            for p,n in zip(s['points'],points):
                n.handle_left_type=p['left']['kind'];n.handle_right_type=p['right']['kind']
        native.material_index=0
        _precision(authored,written,o['id'])
        _precision([p['position'] for p in s['points']],[list(n.co)[:3] for n in points],o['id'],s['closed'])
        if s['kind']=='BEZIER':
            for p,n in zip(s['points'],points):
                for side in ('left','right'):
                    if 'position' in p[side]:_edge_precision(p['position'],p[side]['position'],list(n.co),list(getattr(n,'handle_'+side)),o['id'])
    return data


def bind(spec,objects,resources):
    for o in spec['objects']:
        if o['kind']!='spline':continue
        data=objects[o['id']].data
        for semantic,prop,ref in [('profile','bevel_object',o['bevel'].get('object','')),('taper','taper_object',o['taper']['object'])]:
            if not ref:continue
            native=resources[ref]
            if native.type!='CURVE':fail('TYPE_MISMATCH',semantic+' requires classic Curve data',o['id'])
            if native.data.dimensions!='2D':fail('INVALID_SPLINE',semantic+' uses local planar XY Curve data',o['id'])
            if semantic=='taper' and (len(native.data.splines)!=1 or native.data.splines[0].use_cyclic_u):fail('INVALID_SPLINE','taper needs one open planar spline',o['id'])
            setattr(data,prop,native)
        data.taper_radius_mode=o['taper']['mode'];data.use_map_taper=o['taper']['mapTrim']


def signature(data):
    """Observe native controls, including automatic handles and inactive defaults.

    Automatic handles and quarter-profile controls are compared with a fresh trusted
    constructor, never persisted witness properties. Analytic qualification is
    separate from this deterministic native-policy verification.
    """
    scalar=(*FIELDS.values(),'fill_mode',*SAMPLING.values(),*TRIM.values(),*PATH.values(),'bevel_mode','bevel_depth','bevel_resolution','taper_radius_mode','use_map_taper')
    result={key:getattr(data,key) for key in scalar};result['splines']=[]
    if data.animation_data or data.shape_keys:fail('VERIFICATION_FAILED','declared static spline data has unexpected animation or shape keys',data.name)
    for s in data.splines:
        item={k:getattr(s,k) for k in ('type',*SPLINE.values(),'order_u','use_endpoint_u','use_bezier_u','material_index','point_count_u','point_count_v')}
        item['points']=[{'co':list(p.co),'radius':p.radius,'tilt':p.tilt,'softbody':p.weight_softbody} for p in s.points]
        item['bezier']=[{'co':list(p.co),'left':list(p.handle_left),'right':list(p.handle_right),'leftType':p.handle_left_type,'rightType':p.handle_right_type,'radius':p.radius,'tilt':p.tilt,'softbody':p.weight_softbody} for p in s.bezier_points]
        result['splines'].append(item)
    if data.bevel_profile:
        profile=data.bevel_profile
        result['profile']={'preset':profile.preset,'clip':profile.use_clip,'even':profile.use_sample_even_lengths,'straight':profile.use_sample_straight_edges,
        'points':[{'position':list(p.location),'left':p.handle_type_1,'right':p.handle_type_2} for p in profile.points]}
    else:result['profile']=None
    return result


def _same(a,b):
    if isinstance(b,dict):return isinstance(a,dict) and a.keys()==b.keys() and all(_same(a[k],v) for k,v in b.items())
    if isinstance(b,list):return isinstance(a,list) and len(a)==len(b) and all(_same(x,y) for x,y in zip(a,b))
    if type(b) in (int,float):return type(a) in (int,float) and math.isfinite(a) and math.isclose(a,b,rel_tol=1e-6,abs_tol=0)
    return type(a) is type(b) and a==b


def _controls_match(actual,expected,identity):
    if len(actual['splines'])!=len(expected['splines']):return False
    for a,b in zip(actual['splines'],expected['splines']):
        positions=[];written=[]
        for family in ('points','bezier'):
            if len(a[family])!=len(b[family]):return False
            if a[family]:
                _precision([q['co'][:3] for q in b[family]],[p['co'][:3] for p in a[family]],identity,b['use_cyclic_u'])
            if family=='bezier':
                for p,q in zip(a[family],b[family]):
                    for side in ('left','right'):_edge_precision(q['co'],q[side],p['co'],p[side],identity)
            for p,q in zip(a[family],b[family]):
                for key in (('co','left','right') if family=='bezier' else ('co',)):
                    positions.append(q[key][:3]);written.append(p[key][:3])
                    # The fourth homogeneous coordinate remains a strict weight.
                    p[key]=q[key][:3]+p[key][3:]
        _precision(positions,written,identity)
    return _same(actual,expected)

def observe(o,obj,objects,resources,material_indices=None):
    if obj.type!='CURVE':fail('VERIFICATION_FAILED','spline object lost classic Curve data',o['id'])
    expected=create(o)
    try:
        if material_indices is not None:
            if len(material_indices)!=len(expected.splines):fail('VERIFICATION_FAILED','material layout spline membership differs',o['id'])
            # Curve clamps material_index against its actual slot count. These
            # temporary slots only enable the independent control comparison;
            # assignment verification separately binds palette pointers/links.
            for material in obj.data.materials:expected.materials.append(material)
            for spline,index in zip(expected.splines,material_indices):spline.material_index=index
        for prop,ref in [('bevel_object',o['bevel'].get('object','')),('taper_object',o['taper']['object'])]:
            if getattr(obj.data,prop)!=(resources[ref] if ref else None):fail('VERIFICATION_FAILED','spline profile/taper pointer identity differs',o['id'])
        expected.taper_radius_mode=o['taper']['mode'];expected.use_map_taper=o['taper']['mapTrim']
        if not _controls_match(signature(obj.data),signature(expected),o['id']):fail('VERIFICATION_FAILED','native spline controls, sampling or sweep settings differ',o['id'])
        # Returning the typed intent here follows complete independent native
        # readback above, including generated handle coordinates and profile.
        from .spline import OPTIONS
        return {key:o[key] for key in OPTIONS}
    finally:bpy.data.curves.remove(expected)
