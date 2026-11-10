"""Resolve typed native pointers and admit bounded geometry dependencies."""
import math
import bpy
from schemaxis.errors import fail
from .mesh_data_native import target
from .node_groups import references

MAXIMUM=2_000_000

def resolve(spec,objects,collections):
    object_map=dict(objects);collection_map=dict(collections);records=[]
    for s in spec.get('geometryResources',[]):
        if s['kind']=='object':
            native=target(s,objects,mesh_only=False);object_map[s['id']]=native
        elif s['kind']=='collection':native=collections[s['collection']];collection_map[s['id']]=native
        else:
            root=objects[s['asset']]
            # Each asset has its actual owned collection containing its carrier
            # and (for ordinary neutral imports) all member Objects. Empty root
            # ObjectInfo alone does not collect ordinary children.
            owners=list(root.users_collection)
            if len(owners)!=1:fail('VERIFICATION_FAILED','whole-asset geometry requires one owned carrier collection',s['asset'])
            native=owners[0];collection_map[s['id']]=native
        records.append({**s,'native':native.name})
    return object_map,collection_map,records


def binding_target(binding,objects):
    root=objects[binding['object']]
    if root.type in ('MESH','CURVE','FONT') and not binding.get('sourceObject'):return root
    return target({'object':binding['object'],'sourceObject':binding.get('sourceObject','')},objects)


def _references(graph,groups):
    result=set(references(graph,'geometry',groups,graph if 'family' in graph else None))
    if 'family' in graph:
        result.update((p['kind'],p.get('default')) for p in graph['inputs']+graph['outputs'] if p['kind'] in ('object','collection') and p.get('default'))
    for node in graph['nodes']:
        if node['kind']=='group':result.update(_references(groups[node['group']],groups))
    return {(kind,ref) for kind,ref in result if kind in ('object','collection')}


def _curves(action,slot):
    if not action or not slot:return []
    result=[]
    for layer in action.layers:
        for strip in layer.strips:
            bag=strip.channelbag(slot)
            if bag:result.extend(bag.fcurves)
    return result


def topology_upper(native,key,spec,*,boolean=False):
    """Bound a finite topology control over the authored timeline before evaluation.

    Single-layer key curves use the Bezier control hull plus timeline endpoints.
    This bounds overshoot and linear extrapolation without sparse frame sampling.
    Dynamic drivers, NLA topology and curve modifiers need a separate declared
    bound; ordinary object/pose deformation animation remains available.
    """
    owner=native.id_data;path=native.path_from_id(key);base=getattr(native,key);animation=owner.animation_data
    if not animation:return int(base)
    drivers=[c for c in animation.drivers if c.data_path==path]
    nla=[c for track in animation.nla_tracks for strip in track.strips for c in _curves(strip.action,strip.action_slot) if c.data_path==path]
    curves=[c for c in _curves(animation.action,animation.action_slot) if c.data_path==path]
    if boolean:return int(bool(base) or bool(drivers or nla or curves))
    if drivers or nla or curves and len(animation.action.layers)!=1:
        fail('UNSUPPORTED_RESOURCE_TOPOLOGY','driven or layered/NLA topology needs an explicit reviewed bound',owner.name,property=path)
    values=[base]
    for curve in curves:
        if curve.modifiers:fail('UNSUPPORTED_RESOURCE_TOPOLOGY','topology curve modifiers need an explicit reviewed bound',owner.name,property=path)
        if any(p.interpolation not in ('CONSTANT','LINEAR','BEZIER') for p in curve.keyframe_points):fail('UNSUPPORTED_RESOURCE_TOPOLOGY','topology interpolation needs a reviewed bound',owner.name,property=path)
        for point in curve.keyframe_points:values.extend((point.co.y,point.handle_left.y,point.handle_right.y))
        values.extend(curve.evaluate(f) for f in (spec.get('frameStart',1),spec.get('frameEnd',250)))
    if any(not math.isfinite(v) for v in values):fail('RESOURCE_BUDGET_EXCEEDED','topology controls must have finite animation bounds',owner.name,property=path)
    return max(0,math.ceil(max(values)))


def _static_topology(native,key):
    """Enum/path policies without a numerical envelope may not vary over time."""
    owner=native.id_data;animation=owner.animation_data
    if not animation:return
    path=native.path_from_id(key)
    curves=[*animation.drivers,*_curves(animation.action,animation.action_slot),*[c for track in animation.nla_tracks for strip in track.strips for c in _curves(strip.action,strip.action_slot)]]
    if any(c.data_path==path for c in curves):fail('UNSUPPORTED_RESOURCE_TOPOLOGY','this resource topology policy must remain static',owner.name,property=path)


def admit(spec,objects,object_map,collection_map):
    """No depsgraph evaluation before dependency and conservative cost checks.

    Resource defaults/overrides in reachable groups are finite pointer candidates;
    all candidates participate in cycle admission. A linked resource socket uses
    the largest candidate cost, never zero. This can conservatively refuse an
    unused default; remove that pointer instead of relying on native dead code.
    """
    graphs={g['id']:g for g in spec['geometryGraphs']};groups={g['id']:g for g in spec['nodeGroups']}
    bindings={};records=[]
    for b in spec['geometryBindings']:
        obj=binding_target(b,objects)
        if obj in bindings:fail('AMBIGUOUS_MESH_TARGET','modifier selectors resolved to the same native Object',b['object'])
        bindings[obj]=graphs[b['graph']];records.append((b,obj))
    refs={g['id']:_references(g,groups) for g in graphs.values()}
    active=set();counts={};active_collections=set();collection_counts={}
    def bounded(count,owner):
        if count>MAXIMUM:fail('RESOURCE_BUDGET_EXCEEDED','geometry resource exceeds two million conservative vertices',owner,estimatedVertices=count)
        return count
    def collection_cost(collection):
        if collection in collection_counts:return collection_counts[collection]
        if collection in active_collections or len(active_collections)>64:fail('DEPENDENCY_CYCLE','geometry collection has recursive membership',collection.name)
        active_collections.add(collection)
        # Count every occurrence, including a child shared under two parents.
        # Deduplicating native IDs here would miss exponential diamond graphs.
        count=bounded(sum(object_cost(o) for o in collection.objects)+sum(collection_cost(c) for c in collection.children),collection.name)
        active_collections.remove(collection);collection_counts[collection]=count;return count
    def object_cost(obj):
        if obj in counts:return counts[obj]
        if obj in active:fail('DEPENDENCY_CYCLE','geometry resources, modifiers or parents form a native dependency cycle',obj.name)
        if len(active)>=64:fail('RESOURCE_BUDGET_EXCEEDED','geometry dependency depth exceeds64 Objects',obj.name)
        active.add(obj)
        # Parent transforms participate even when geometry is requested Original.
        if obj.parent:object_cost(obj.parent)
        for c in obj.constraints:
            t=getattr(c,'target',None)
            if t and t!=obj:object_cost(t)
        if obj.instance_type not in ('NONE','COLLECTION'):fail('UNSUPPORTED_RESOURCE_TOPOLOGY','native vertex/face instancing needs a reviewed occurrence bound',obj.name)
        if obj.type=='MESH':count=max(len(obj.data.vertices),len(obj.data.loops),2*len(obj.data.edges))
        elif obj.type=='CURVE':
            data=obj.data
            for key in ('bevel_mode','dimensions','fill_mode','fill_solver','fill_rule'):_static_topology(data,key)
            sampling=max(1,topology_upper(data,'resolution_u',spec),topology_upper(data,'render_resolution_u',spec))
            path_count=sum(max(len(s.points),len(s.bezier_points))*(1 if s.type=='POLY' else max(sampling,topology_upper(s,'resolution_u',spec))) for s in data.splines)
            profile_count=max(4,4*(topology_upper(data,'bevel_resolution',spec)+1))
            if data.bevel_mode=='PROFILE' and data.bevel_profile:
                profile_count=max(profile_count,4*len(data.bevel_profile.points)*(topology_upper(data,'bevel_resolution',spec)+1))
            if data.bevel_mode=='OBJECT' and data.bevel_object:
                profile=data.bevel_object
                if profile.type!='CURVE':fail('UNSUPPORTED_RESOURCE_TOPOLOGY','curve bevel source must have classic Curve data',obj.name)
                object_cost(profile)  # dependency admission before any evaluation
                profile_sampling=max(1,topology_upper(profile.data,'resolution_u',spec),topology_upper(profile.data,'render_resolution_u',spec))
                profile_count=max(1,sum(max(len(s.points),len(s.bezier_points))*(1 if s.type=='POLY' else max(profile_sampling,topology_upper(s,'resolution_u',spec))) for s in profile.data.splines))*4
            if data.taper_object:
                if data.taper_object.type!='CURVE':fail('UNSUPPORTED_RESOURCE_TOPOLOGY','curve taper source must have classic Curve data',obj.name)
                object_cost(data.taper_object)
            count=path_count*profile_count*4
            # CDT may introduce intersection vertices for self-crossing planar
            # contours. A pairwise intersection bound avoids a linear claim.
            if data.dimensions=='2D' and data.fill_mode!='NONE' and data.fill_solver=='CDT':count=max(count,4*path_count*path_count)
        elif obj.type=='FONT':
            if any(f and f.filepath!='<builtin>' for f in (obj.data.font,obj.data.font_bold,obj.data.font_italic,obj.data.font_bold_italic)):fail('UNSUPPORTED_RESOURCE_TOPOLOGY','custom font outlines need a reviewed geometry expansion bound',obj.name)
            sampling=max(1,topology_upper(obj.data,'resolution_u',spec),topology_upper(obj.data,'render_resolution_u',spec))
            data=obj.data;_static_topology(data,'bevel_mode');resolution=topology_upper(data,'bevel_resolution',spec)
            section=(resolution+1)**2*2
            if data.bevel_mode=='PROFILE' and data.bevel_profile:section=max(section,4*len(data.bevel_profile.points)*(resolution+1))
            if data.bevel_mode=='OBJECT' and data.bevel_object:
                profile=data.bevel_object
                if profile.type!='CURVE':fail('UNSUPPORTED_RESOURCE_TOPOLOGY','font bevel source must have classic Curve data',obj.name)
                object_cost(profile)
                profile_sampling=max(1,topology_upper(profile.data,'resolution_u',spec),topology_upper(profile.data,'render_resolution_u',spec))
                section=max(section,4*sum(max(len(s.points),len(s.bezier_points))*(1 if s.type=='POLY' else max(profile_sampling,topology_upper(s,'resolution_u',spec))) for s in profile.data.splines))
            if data.taper_object:object_cost(data.taper_object)
            count=max(1,len(data.body))*4096*sampling*section
        elif obj.instance_collection:count=collection_cost(obj.instance_collection)
        else:
            if obj.type not in ('EMPTY','LIGHT','CAMERA','ARMATURE','SPEAKER','LIGHT_PROBE'):fail('UNSUPPORTED_RESOURCE_TOPOLOGY','resource geometry type needs a reviewed expansion bound',obj.name,type=obj.type)
            count=0
        if obj.instance_collection and obj.type in ('MESH','CURVE','FONT'):count+=collection_cost(obj.instance_collection)
        for m in obj.modifiers:
            if not (topology_upper(m,'show_viewport',spec,boolean=True) or topology_upper(m,'show_render',spec,boolean=True)):continue
            for key in ('object','target','offset_object','mirror_object','start_cap','end_cap'):
                dependency=getattr(m,key,None)
                if isinstance(dependency,bpy.types.Object) and dependency!=obj:object_cost(dependency)
            if m.type in ('SUBSURF','MULTIRES'):
                levels=max(topology_upper(m,k,spec) for k in (('levels','render_levels','sculpt_levels') if m.type=='MULTIRES' else ('levels','render_levels')))
                if count and levels>10:fail('RESOURCE_BUDGET_EXCEEDED','subdivision animation exceeds the resource expansion budget',obj.name)
                if count:count*=6*4**levels
            elif m.type=='ARRAY':
                _static_topology(m,'fit_type')
                if m.fit_type!='FIXED_COUNT':fail('UNSUPPORTED_RESOURCE_TOPOLOGY','resource array needs a fixed bounded count',obj.name)
                count=count*topology_upper(m,'count',spec)+sum(object_cost(c) for c in (m.start_cap,m.end_cap) if c)
            elif m.type=='MIRROR':count*=32  # all axes and bisect cuts, including animated toggles
            elif m.type=='SOLIDIFY':count*=3
            elif m.type=='BEVEL':count*=6*(topology_upper(m,'segments',spec)+1)**2
            elif m.type=='TRIANGULATE':count*=6
            elif m.type=='BOOLEAN':
                _static_topology(m,'operand_type')
                if m.operand_type!='OBJECT' or not m.object:fail('UNSUPPORTED_RESOURCE_TOPOLOGY','resource boolean needs a finite Object operand',obj.name)
                count=6*max(1,count)*max(1,object_cost(m.object))
            elif m.type not in ('ARMATURE','CAST','CORRECTIVE_SMOOTH','CURVE','DATA_TRANSFER','DECIMATE','DISPLACE','EDGE_SPLIT','HOOK','LAPLACIANDEFORM','LAPLACIANSMOOTH','LATTICE','MESH_DEFORM','NORMAL_EDIT','SHRINKWRAP','SIMPLE_DEFORM','SMOOTH','SMOOTH_BY_ANGLE','SURFACE_DEFORM','UV_PROJECT','UV_WARP','VERTEX_WEIGHT_EDIT','VERTEX_WEIGHT_MIX','VERTEX_WEIGHT_PROXIMITY','WARP','WAVE','WEIGHTED_NORMAL','WELD'):
                fail('UNSUPPORTED_RESOURCE_TOPOLOGY','imported resource modifier needs a reviewed expansion bound',obj.name,modifier=m.type)
            if m.type=='EDGE_SPLIT':count*=6
            bounded(count,obj.name)
        if obj in bindings:
            graph=bindings[obj];resource_counts={}
            for kind,ref in refs[graph['id']]:
                resource_counts[(kind,ref)]=object_cost(object_map[ref]) if kind=='object' else collection_cost(collection_map[ref])
            for kind in ('object','collection'):
                resource_counts[(kind,'*')]=max([v for (k,r),v in resource_counts.items() if k==kind]+[0])
            from .node_catalogue import geometry_budget
            values=geometry_budget(graph,count,groups=groups,resource_counts=resource_counts)
            count=values[next(n['id'] for n in graph['nodes'] if n['kind']=='output')]
        active.remove(obj);counts[obj]=bounded(count,obj.name);return count
    for obj in bindings:object_cost(obj)
    authored=[objects[o['id']] for o in spec['objects'] if o['kind']=='spline']
    bounded(sum(object_cost(o) for o in authored),'authored spline geometry')
    return records


def observe_bindings(spec,objects):
    result=[]
    for b in spec['geometryBindings']:
        obj=binding_target(b,objects);modifier=obj.modifiers.get('schemaxis-geometry-'+b['graph'])
        if modifier is None or modifier.type!='NODES' or not modifier.show_viewport or not modifier.show_render or not modifier.node_group:fail('VERIFICATION_FAILED','geometry binding modifier is absent or disabled',obj.name)
        result.append({**b,'graph':modifier.node_group.name})
    return result
