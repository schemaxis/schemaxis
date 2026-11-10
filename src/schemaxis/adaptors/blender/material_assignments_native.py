"""Editable DATA layouts and OBJECT palettes with fresh-source verification."""
import copy
import bpy
from schemaxis.errors import fail
from . import material_assignments as policy


def target(s,objects):
    root=objects[s['object']]
    if root.type in ('MESH','CURVE','FONT') and not s['sourceObject']:return root
    if s['sourceObject']:
        from .mesh_data_native import target as selected
        obj=selected(s,objects,mesh_only=False)
        if obj.type in ('MESH','CURVE','FONT'):return obj
    elif 'schemaxisAssetMembers' in root:
        from .production_asset_collections import asset_members
        members=[o for o in asset_members(root) if o.type in ('MESH','CURVE','FONT')]
        if len(members)==1:return members[0]
    fail('AMBIGUOUS_MATERIAL_TARGET','select exactly one Mesh, classic Curve or text source part',s['object'])


def domain(obj):
    if obj.type=='MESH':return 'FACE',obj.data.polygons
    if obj.type=='CURVE':return 'SPLINE',obj.data.splines
    if obj.type=='FONT':return 'CHARACTER',obj.data.body_format
    fail('TYPE_MISMATCH','material assignments require Mesh, classic Curve or text',obj.name)


def spline_names(s,spec):
    current=s['object'];seen=set();by_id={o['id']:o for o in spec['objects']}
    while current in by_id and current not in seen:
        seen.add(current);o=by_id[current]
        if o['kind']=='spline':return [sp['id'] for sp in o['splines']]
        if o['kind']!='instance':break
        current=o['source']
    return []


def indices(s,obj,spec):
    kind,elements=domain(obj)
    if len(elements)>100000:fail('RESOURCE_BUDGET_EXCEEDED','material surface elements exceed bounded policy',s['id'])
    geometry=None
    if kind=='FACE':
        from .mesh_edits_native import geometry as read_geometry
        geometry=read_geometry(obj.data)
    return policy.indices(s,kind,len(elements),geometry,spline_names(s,spec))


def build(spec,objects,materials,legacy_data):
    plans=[];resolved=set();shared=set();total=0
    for s in spec.get('materialAssignments',[]):
        obj=target(s,objects)
        if obj in resolved:fail('AMBIGUOUS_MATERIAL_TARGET','different material selectors resolve to one Object',s['id'])
        resolved.add(obj)
        if obj.data in legacy_data:fail('INVALID_MATERIAL_ASSIGNMENT','legacy materialBindings and materialAssignments cannot write the same data; use one named layout and palettes',s['id'])
        if s['kind']=='override':continue
        owners=[o for o in bpy.data.objects if o.data==obj.data]
        if s['sharing']=='refuse' and len(owners)>1:fail('SHARED_MATERIAL_DATA','surface layout needs explicit copy or shared ownership',s['id'])
        if s['sharing']!='copy':
            if obj.data in shared:fail('SHARED_MATERIAL_DATA','multiple layouts write the same shared data; combine or copy explicitly',s['id'])
            shared.add(obj.data)
        total+=policy.selection_work(s,len(domain(obj)[1]))+len(owners)*len(s['slots'])
        if total>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate material assignment exceeds one million elements/owner slots')
        values=indices(s,obj,spec)
        plans.append((s,obj,values))
    copies={obj for s,obj,_ in plans if s['sharing']=='copy'}
    def final_group(obj):return ('copy',obj.as_pointer()) if obj in copies else ('shared',obj.data.as_pointer()) if obj.data else ('object',obj.as_pointer())
    layouts_by_id={s['id']:(s,obj) for s,obj,_ in plans}
    total=0
    for s in spec.get('materialAssignments',[]):
        obj=target(s,objects)
        if s['kind']=='override':
            _,source=layouts_by_id[s['layout']]
            if obj==source or final_group(obj)!=final_group(source):fail('MATERIAL_LAYOUT_IDENTITY','Object palette requires a distinct Object sharing the referenced layout data ID',s['id'])
        owners=[o for o in bpy.data.objects if final_group(o)==final_group(obj)]
        total+=len(domain(obj)[1])+len(owners)*len(s['slots'])
        if len(owners)>4096 or total>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate material readback exceeds one million elements/owner slots')
    saved=[]
    for s,obj,values in sorted(plans,key=lambda p:p[0]['sharing']!='copy'):
        original=obj.data;native=original.copy()
        affected=[o for o in bpy.data.objects if o.data==original] if s['sharing']=='shared' else [obj]
        for owner in affected:
            saved.append((owner,original,[(slot.link,slot.material) for slot in owner.material_slots],owner.active_material_index))
            owner.data=native
        native.materials.clear()
        for slot in s['slots']:native.materials.append(materials[slot['material']])
        for owner in affected:
            for slot in owner.material_slots:slot.link='DATA'
            owner.active_material_index=0
        for element,value in zip(domain(obj)[1],values):element.material_index=value
        if hasattr(native,'update'):native.update()
    layouts={s['id']:(s,target(s,objects)) for s in spec.get('materialAssignments',[]) if s['kind']=='layout'}
    for s in spec.get('materialAssignments',[]):
        if s['kind']!='override':continue
        obj=target(s,objects);layout,source=layouts[s['layout']]
        if obj==source or obj.data!=source.data:fail('MATERIAL_LAYOUT_IDENTITY','Object palette requires a distinct Object sharing the referenced layout data ID',s['id'])
        if len(obj.material_slots)!=len(layout['slots']):fail('MATERIAL_LAYOUT_IDENTITY','Object palette slot layout differs',s['id'])
        saved.append((obj,obj.data,[(slot.link,slot.material) for slot in obj.material_slots],obj.active_material_index))
        palette={slot['id']:materials[slot['material']] for slot in s['slots']}
        for logical,native in zip(layout['slots'],obj.material_slots):native.link='OBJECT';native.material=palette[logical['id']]
        obj.active_material_index=0
    return saved


def restore(saved):
    for obj,data,slots,active in reversed(saved):
        current=obj.data;obj.data=data
        for native,(link,material) in zip(obj.material_slots,slots):
            native.link=link
            if link=='OBJECT':native.material=material
        obj.active_material_index=active
        if current!=data and current.users==0:
            (bpy.data.meshes if isinstance(current,bpy.types.Mesh) else bpy.data.curves).remove(current)


def observe(spec,objects):
    records=[];total=0;layouts={s['id']:s for s in spec.get('materialAssignments',[]) if s['kind']=='layout'}
    for s in spec.get('materialAssignments',[]):
        obj=target(s,objects);kind,elements=domain(obj)
        if not 0<len(elements)<=100000 or len(obj.material_slots)>256:fail('VERIFICATION_FAILED','material surface/slot count exceeds policy',s['id'])
        layout=s if s['kind']=='layout' else layouts[s['layout']]
        if s['kind']=='override' and obj.data!=target(layout,objects).data:fail('VERIFICATION_FAILED','Object palette no longer shares its declared layout data ID',s['id'])
        logical=[v['id'] for v in layout['slots']]
        def slots(owner):return [{'link':slot.link,'material':slot.material.name if slot.material else None} for slot in owner.material_slots]
        owners=sorted((o for o in bpy.data.objects if o.data==obj.data),key=lambda o:o.name)
        total+=len(elements)+len(owners)*len(obj.material_slots)
        if len(owners)>4096 or total>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate material readback exceeds one million elements/owner slots',s['id'])
        records.append({**{k:s[k] for k in ('id','kind','object','sourceObject')},'nativeObject':obj.name,'domain':kind,
            'logicalSlots':logical,'slots':[{'id':logical[i] if i<len(logical) else None,'material':slot.material.name if slot.material else None} for i,slot in enumerate(obj.material_slots)],
            'links':[slot.link for slot in obj.material_slots],'dataMaterials':[m.name if m else None for m in obj.data.materials],
            'indices':[e.material_index for e in elements],'owners':[o.name for o in owners],
            'ownerSlots':{o.name:slots(o) for o in owners}})
    return records


def expected_spline_indices(spec,objects,obj):
    for s in spec.get('materialAssignments',[]):
        if s['kind']=='layout' and target(s,objects).data==obj.data:return indices(s,obj,spec)
    return None


def references(master,selection,prepared,visit,sources):
    spec=master.document['scenes'][0].get('production')
    if not spec or not spec.get('materialAssignments'):return None
    from .native import Backend,configure_render
    from .production_native import Production
    from schemaxis.pipeline import RuntimeClosure
    bpy.ops.wm.read_factory_settings(use_empty=True);scene=bpy.context.scene
    configure_render(scene,{**prepared['renderSettings'],'device':'CPU'})
    camera=bpy.data.objects.new('__schemaxis_camera',bpy.data.cameras.new('__schemaxis_camera'));scene.collection.objects.link(camera);scene.camera=camera
    active=RuntimeClosure(master,Backend(sources));active.activate(selection.roots);active.apply(visit)
    production=Production(copy.deepcopy(spec),active.handles,sources)
    # No submitted .blend, persisted witness, native pointer or caller palette
    # participates in this reference. Only immutable values survive open_mainfile.
    return observe(spec,production.objects)


def verify(actual,expected):
    if expected is not None and actual.get('materialAssignments')!=expected:
        fail('VERIFICATION_FAILED','surface materials differ from trusted authored/captured-source reconstruction')
