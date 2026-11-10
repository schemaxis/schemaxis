"""Explicit top-level captured-asset realization for per-layer part policies.

The source file remains immutable. Fresh imported mesh/material/action IDs and
collection links are retained; only the consumer carrier is realized. Native
constraints/GNodes and nested instance carriers require a separate equivalence
contract and refuse here rather than silently changing their coordinate space.
"""
from schemaxis.errors import fail
from mathutils import Matrix


def requested(spec):
    result = {}
    for layer in spec.get('viewLayers', []):
        for rule in layer['collections']:
            target = rule['target']
            if target['kind'] == 'asset' and target.get('path'):
                result.setdefault(target['asset'], set()).add(tuple(target['path']))
    return result


def realize(spec, sources):
    result = {}
    for asset, paths in requested(spec).items():
        source = sources.get(asset)
        if source is None:fail('UNKNOWN_REFERENCE','fresh source projection capability is absent',asset)
        root, carrier = source['root'], source['carrier']
        owned = set(source['dependencies']);members = set(source['objects'])
        ancestors = set(members)
        for obj in members:
            parent = obj.parent;depth=0
            while parent is not None:
                depth+=1
                if depth>128:fail('RESOURCE_BUDGET_EXCEEDED','source projection parent chain exceeds128',obj.name)
                if parent not in owned:fail('UNSUPPORTED_RENDER_PROJECTION','source parent is outside admitted original ownership',obj.name)
                ancestors.add(parent);parent = parent.parent
        for obj in ancestors:
            if obj.constraints or obj.instance_type == 'COLLECTION' or any(mod.type in {'NODES','ARMATURE','LATTICE','MESH_DEFORM','SURFACE_DEFORM'} for mod in obj.modifiers):
                fail('UNSUPPORTED_RENDER_PROJECTION','nested instances and coordinate-dependent constraints/deformers need their explicit projection equivalence contract',obj.name)
            if obj.animation_data and obj.animation_data.drivers:
                fail('UNSUPPORTED_RENDER_PROJECTION','source object drivers need a reviewed projection dependency contract',obj.name)
        targets = {}
        def visit(collection, path=(), suffix=(), depth=0):
            if depth>64 or len(targets)>1024:fail('RESOURCE_BUDGET_EXCEEDED','source layer projection exceeds bounded hierarchy',asset)
            if path in targets:fail('AMBIGUOUS_RENDER_COLLECTION','source hierarchy repeats a logical part path',asset,path=list(path))
            targets[path]={'collection':collection,'suffix':(source['container'].name,carrier.name,*suffix)}
            for child in collection.children:
                identity=source['sourceCollections'].get(child)
                if identity is None:fail('VERIFICATION_FAILED','source collection lacks its fresh original identity',child.name)
                visit(child,(*path,identity),(*suffix,child.name),depth+1)
        visit(carrier)
        if paths-set(targets):fail('UNKNOWN_REFERENCE','source part path is absent from the admitted hierarchy',asset,paths=[list(p) for p in sorted(paths-set(targets))])
        # All validation precedes mutation. Ordinary local TRS Action channels
        # keep their original basis and shared Actions; the asset carrier adds
        # the same outer transform previously supplied by collection instancing.
        for obj in ancestors:
            if obj.parent is None:
                basis=obj.matrix_basis.copy();obj.parent=root
                obj.matrix_parent_inverse=Matrix.Identity(4);obj.matrix_basis=basis
        root.instance_type='NONE';root.instance_collection=None
        source['container'].children.link(carrier)
        for path,target in targets.items():result[(asset,path)]=target
    return result
