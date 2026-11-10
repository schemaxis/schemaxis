"""Closed native scene selection and collection-instance ownership.

A selected view layer becomes an owned collection carrier. Source objects keep
parents, shared data and collection-instance references; excluded branches never
become visible carrier members. No source scene settings are installed globally.
"""
import json
import bpy
from schemaxis.errors import fail


def collection_closure(collection):
    objects=set();collections=set();active=set()
    def visit(c,depth=0):
        if depth>64:fail('RESOURCE_BUDGET_EXCEEDED','collection ownership exceeds 64 nested levels',c.name)
        if c in active:fail('DEPENDENCY_CYCLE','collection instances contain a recursive dependency',c.name)
        if c in collections:return
        collections.add(c);active.add(c)
        if len(collections)>1024:fail('RESOURCE_BUDGET_EXCEEDED','asset exceeds 1024 owned collections')
        objects.update(c.objects)
        if len(objects)>4096:fail('RESOURCE_BUDGET_EXCEEDED','asset exceeds 4096 owned objects')
        for child in c.children:visit(child,depth+1)
        for obj in c.objects:
            if obj.instance_type=='COLLECTION':
                if not obj.instance_collection:fail('INVALID_ASSET','collection instance has no collection',obj.name)
                visit(obj.instance_collection,depth+1)
        active.remove(c)
    visit(collection)
    return objects,collections


def asset_members(root):
    if root.instance_type=='COLLECTION':return sorted(collection_closure(root.instance_collection)[0],key=lambda o:o.name)
    # The imported members remain distinct from objects authored later beneath
    # the asset root through ordinary production hierarchy composition.
    try:records=json.loads(root['schemaxisAssetMembers'])
    except (KeyError,ValueError,TypeError):fail('VERIFICATION_FAILED','asset ownership manifest is absent',root.name)
    descendants=set(root.children_recursive);members=[]
    for r in records:
        obj=bpy.data.objects.get(r['name'])
        if obj is None or obj not in descendants:fail('VERIFICATION_FAILED','imported asset membership differs',root.name)
        members.append(obj)
    if len(members)!=len(set(members)):fail('VERIFICATION_FAILED','asset ownership repeats an object',root.name)
    return sorted(members,key=lambda o:o.name)


def _selection(available,requested,kind):
    if requested:
        if requested not in available:fail('UNKNOWN_ASSET_SELECTION','named native asset selection is absent',kind,requested=requested,available=list(available))
        return requested
    if len(available)!=1:fail('AMBIGUOUS_ASSET_SELECTION','choose the native asset '+kind+' explicitly',kind,available=list(available))
    return available[0]


POOLS=('objects','collections','meshes','materials','images','actions','armatures','curves','fonts','cameras','lights','worlds','node_groups','scenes','texts','lattices','volumes','metaballs','shape_keys','sounds','movieclips','masks','particles','textures','grease_pencils','pointclouds','hair_curves','linestyles','brushes','workspaces','screens','speakers','lightprobes','cache_files','palettes','paint_curves','window_managers')


def prune_imported(ownership,keep):
    # Prune only IDs appended for this import, after the complete finite proof.
    # Unselected view-layer branches must not leak into the packed deliverable.
    appended=set().union(*ownership['importedIds'].values())
    # Object parent/constraint pointers can be weak users. Appending clears
    # source fake-user flags; retain needed zero-user IDs so save/reopen cannot
    # silently erase an otherwise captured dependency.
    for item in appended & keep:
        if item.users==0:item.use_fake_user=True
    discard=appended-keep
    if discard:bpy.data.batch_remove(ids=discard)


def load_scene(source,spec,*,capture_collection_paths=False):
    prior={name:set(getattr(bpy.data,name)) for name in POOLS if hasattr(bpy.data,name)}
    before_objects=set(bpy.data.objects);before_collections=set(bpy.data.collections);before_scenes=set(bpy.data.scenes)
    with bpy.data.libraries.load(str(source),link=False) as (available,selected):
        scenes=list(available.scenes)
        if not scenes:
            if spec['scene'] or spec['viewLayer']:fail('UNKNOWN_ASSET_SELECTION','object-only library has no scene or view layer')
            if not available.objects or len(available.objects)>4096:fail('RESOURCE_BUDGET_EXCEEDED','native object library requires 1–4096 objects',spec['id'])
            selected.objects=list(available.objects);scene_name=None
        else:
            scene_name=_selection(scenes,spec['scene'],'scene');selected.scenes=[scene_name]
            if capture_collection_paths:
                # The native library loader replaces selected list entries
                # IN PLACE with appended IDs. Keep original logical names in
                # an immutable separate sequence, including suffix collisions.
                source_collection_names=tuple(available.collections)
                if len(source_collection_names)>1024:fail('RESOURCE_BUDGET_EXCEEDED','source projection exceeds1024 collection identities',spec['id'])
                selected.collections=list(source_collection_names)
    source_collections={native:identity for identity,native in zip(source_collection_names,selected.collections) if native is not None} if scene_name is not None and capture_collection_paths else {}
    imported_ids={name:set(getattr(bpy.data,name))-before for name,before in prior.items()}
    if scene_name is None:
        if set(bpy.data.collections)-before_collections:fail('UNSUPPORTED_ASSET_DEPENDENCY','object-only libraries with collection dependencies require a scene carrier',spec['id'])
        return {'objects':[o for o in selected.objects if o],'carrier':None,'selection':{'mode':'objectLibrary','scene':'','viewLayer':''},'importedScenes':set(),'importedIds':imported_ids}
    scene=selected.scenes[0];layers=[layer.name for layer in scene.view_layers]
    layer_name=_selection(layers,spec['viewLayer'],'viewLayer');layer=scene.view_layers[layer_name]
    if layer.material_override:fail('UNSUPPORTED_ASSET_DEPENDENCY','apply or remove view-layer material overrides before asset reuse',layer_name)
    excluded=[];projections=[];masks={};memo={}
    if any(obj.hide_get(view_layer=layer) for obj in layer.objects):fail('UNSUPPORTED_ASSET_DEPENDENCY','local view-layer object hiding must be converted to collection exclusions or data visibility before reuse',layer_name)
    def inspect(lc,path=(),depth=0):
        if depth>64:fail('RESOURCE_BUDGET_EXCEEDED','view-layer projection exceeds 64 levels')
        if lc.hide_viewport:fail('UNSUPPORTED_ASSET_DEPENDENCY','local view-layer collection hiding must be converted to exclusions or data visibility before reuse',lc.name)
        if lc.holdout or lc.indirect_only:fail('UNSUPPORTED_ASSET_DEPENDENCY','view-layer holdout and indirect-only policies require a compositing handoff',lc.name)
        mask=[]
        for child in lc.children:
            child_path=(*path,child.name)
            if child.exclude:
                excluded.append(list(child_path));mask.append((child.collection.as_pointer(),False))
            else:mask.append((child.collection.as_pointer(),inspect(child,child_path,depth+1)))
        masks[lc.as_pointer()]=tuple(mask)
        return tuple(mask)
    inspect(layer.layer_collection)
    def needs_projection(lc):
        return any(child.exclude or needs_projection(child) for child in lc.children)
    def clone(lc):
        if not lc.collection.is_embedded_data and not needs_projection(lc):return lc.collection
        key=(lc.collection.as_pointer(),masks[lc.as_pointer()])
        if key in memo:return memo[key]
        if lc.collection.is_embedded_data:
            c=bpy.data.collections.new(spec['id']+'--view--'+lc.collection.name)
            for obj,link in zip(lc.collection.objects,lc.collection.collection_objects):
                c.objects.link(obj);next(edge for native,edge in zip(c.objects,c.collection_objects) if native==obj).light_linking.link_state=link.light_linking.link_state
            c.hide_render=lc.collection.hide_render;c.hide_viewport=lc.collection.hide_viewport;c.hide_select=lc.collection.hide_select;c.color_tag=lc.collection.color_tag
            for name,value in lc.collection.items():c[name]=value
        else:
            c=lc.collection.copy();c.name=spec['id']+'--view--'+lc.collection.name
        memo[key]=c;projections.append({'source':lc.collection.name,'carrier':c.name})
        if capture_collection_paths:source_collections[c]=source_collections.get(lc.collection,lc.collection.name)
        for child in list(c.children):c.children.unlink(child)
        for child in lc.children:
            if not child.exclude:
                mapped=clone(child);c.children.link(mapped)
                next(edge for native,edge in zip(c.children,c.collection_children) if native==mapped).light_linking.link_state=next(edge for native,edge in zip(lc.collection.children,lc.collection.collection_children) if native==child.collection).light_linking.link_state
        return c
    carrier=clone(layer.layer_collection);carrier.instance_offset=(0,0,0)
    objects,collections=collection_closure(carrier)
    # Selection is geometric/asset ownership. Render engine, passes, world and
    # camera remain the consumer's explicit scene contract; action frame indices
    # are preserved rather than implicitly retimed to a different consumer FPS.
    selection={'mode':'scene','scene':scene_name,'viewLayer':layer_name,'excluded':excluded,'projections':projections,
      'sourceFps':scene.render.fps/scene.render.fps_base,'sourceFrameRange':[scene.frame_start,scene.frame_end]}
    return {'objects':sorted(objects,key=lambda o:o.name),'carrier':carrier,'selection':selection,
      'sourceCollections':source_collections,
      'importedScenes':set(bpy.data.scenes)-before_scenes,'importedObjects':set(bpy.data.objects)-before_objects,'importedIds':imported_ids}
