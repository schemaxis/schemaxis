"""Bind reserved editor attributes when a material requests their values.

Ordinary selection is presentation state. An Attribute shader can request the
same native flags, however, making them source-owned material inputs. These
fresh-only signatures do not alter retained asset-fidelity/v2 records.
"""
import bpy
from .material_inputs_native import SELECTION_ATTRIBUTES

GEOMETRY_TYPES={'MESH','CURVE','SURFACE','FONT'}


def objects():
    # Fresh construction has pruned unused imported objects. Include retained
    # asset members, collection instances and node-resource dependencies, not
    # just the production route's logical root objects.
    return {o.name:o for o in bpy.data.objects if o.type in GEOMETRY_TYPES}


def observe(owned,snapshot,graph):
    analyses={}
    cache={}
    def resource_objects(owner):
        result={owner,*owner.children_recursive}
        from .production_asset_collections import collection_closure
        for obj in list(result):
            if obj.instance_type=='COLLECTION' and obj.instance_collection:
                result.update(collection_closure(obj.instance_collection)[0])
        return {obj.name for obj in result if obj.type in GEOMETRY_TYPES}
    def scan_one(roots):
        pending=list(roots);seen=set();names=set();dependencies=set();attributes=set()
        while pending:
            value=pending.pop();snapshot.budget()
            if isinstance(value,bpy.types.ID):
                if value.is_evaluated:value=value.original
                if value in seen:continue
                seen.add(value)
                if value in cache:
                    requested,targets,paths=cache[value];names.update(requested);dependencies.update(targets);attributes.update(paths);continue
                if isinstance(value,bpy.types.Object):dependencies.update(resource_objects(value))
                elif isinstance(value,bpy.types.Collection):
                    from .production_asset_collections import collection_closure
                    for obj in collection_closure(value)[0]:dependencies.update(resource_objects(obj))
                elif isinstance(value,bpy.types.Material):
                    if value.node_tree:pending.append(value.node_tree)
                elif isinstance(value,bpy.types.NodeTree):
                    if value.bl_idname not in ('ShaderNodeTree','GeometryNodeTree'):
                        snapshot.reject('material selection inputs require reviewed shader/geometry trees',value.name)
                    for node in value.nodes:
                        snapshot.budget()
                        # attribute_type is animatable in the reviewed runtime:
                        # OBJECT now can become GEOMETRY on a future frame. The
                        # literal attribute_name is not animatable. Bind reserved
                        # names regardless of the current mode, conservatively
                        # retaining source flags for every admitted Action.
                        if node.bl_idname=='ShaderNodeAttribute':
                            attributes.add(node.attribute_name)
                            if node.attribute_name in SELECTION_ATTRIBUTES:names.add(node.attribute_name)
                        if node.bl_idname=='ShaderNodeVertexColor' and node.layer_name in SELECTION_ATTRIBUTES:
                            names.add(node.layer_name)
                        pending.extend(references(node))
                        for socket in (*node.inputs,*node.outputs):
                            if hasattr(socket,'default_value'):pending.append(socket.default_value)
                    for item in value.interface.items_tree:
                        if hasattr(item,'default_value'):pending.append(item.default_value)
            elif isinstance(value,dict) or hasattr(value,'items'):
                pending.extend(v for _,v in value.items())
            elif isinstance(value,(list,tuple)):
                pending.extend(value)
        return names,dependencies,attributes
    def scan(roots):
        names=set();dependencies=set();attributes=set()
        for root in roots:
            if isinstance(root,bpy.types.ID):
                if root.is_evaluated:root=root.original
                if root not in cache:cache[root]=scan_one([root])
                requested,targets,paths=cache[root]
            else:requested,targets,paths=scan_one([root])
            names.update(requested);dependencies.update(targets);attributes.update(paths)
        return names,dependencies,attributes
    def references(native):
        return [getattr(native,p.identifier) for p in native.bl_rna.properties
                if p.type=='POINTER' and isinstance(getattr(native,p.identifier),bpy.types.ID)]
    for name,obj in sorted(owned.items()):
        snapshot.location=name
        if obj.type not in GEOMETRY_TYPES or obj.data is None:
            snapshot.reject('material selection source geometry type differs',name)
        roots=[*obj.data.materials,*(s.material for s in obj.material_slots)]
        for modifier in obj.modifiers:
            roots.extend(references(modifier))
            try:roots.extend(v for _,v in modifier.items())
            except TypeError:pass  # This reviewed native modifier cannot own IDProperties.
        evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=graph)
        try:roots.extend(m.original if m and m.is_evaluated else m for m in mesh.materials)
        finally:evaluated.to_mesh_clear()
        names,dependencies,attributes=scan(roots)
        if dependencies-set(owned):
            snapshot.reject('material selection dependency is outside reconstructed geometry membership',name)
        analyses[name]={'names':names,'dependencies':dependencies,'attributes':attributes}
    # A modifier may bring selected source attributes through Object/Collection
    # geometry resources. Conservatively propagate queries along all admitted
    # resource alternatives, including renderer-only modifier branches.
    pending=[n for n,a in analyses.items() if a['names'] or a['attributes']]
    while pending:
        name=pending.pop();names=analyses[name]['names'];attributes=analyses[name]['attributes']
        for target in analyses[name]['dependencies']:
            extra=names-analyses[target]['names']
            paths=attributes-analyses[target]['attributes']
            if extra or paths:
                analyses[target]['names'].update(extra);analyses[target]['attributes'].update(paths);pending.append(target)
    def flags(mesh,names):
        result={}
        for name in sorted(names):
            native=mesh.attributes.get(name)
            if native is None:result[name]=None;continue
            if native.data_type!='BOOLEAN':
                snapshot.reject('reserved material selection attributes require native Boolean flags',name)
            result[name]={'domain':native.domain,'values':snapshot.payload(v.value for v in native.data)}
        return result
    result={}
    for name,obj in sorted(owned.items()):
        names=analyses[name]['names'];snapshot.location=name
        row={'requested':sorted(names)}
        if names:
            row['stored']=flags(obj.data,names) if obj.type=='MESH' else None
            evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=graph)
            try:row['evaluated']=flags(mesh,names)
            finally:evaluated.to_mesh_clear()
        result[name]=row
    from .attribute_inputs_native import observe as observe_attributes
    attributes=set().union(*(a['attributes'] for a in analyses.values()))
    return result,observe_attributes(attributes,snapshot) if attributes else {}
