"""Fresh numeric inputs to the existing Attribute shader, without authoring RNA.

Blender's Object/Instancer/View Layer modes may read a built-in RNA path as
well as an ID property. Bind each candidate independently: lookup precedence
and future animated mode changes must not hide a source-owned numeric value.
"""
import math
import bpy


def observe(names, snapshot):
    def value(owner, name):
        snapshot.budget(len(name))
        if len(name)>1024:
            snapshot.reject('material attribute lookup exceeds 1024 characters',name[:64])
        try:
            candidate=owner[name] if name in owner else owner.path_resolve(name)
        except (KeyError,TypeError,ValueError,AttributeError):return None
        if isinstance(candidate,(bool,int,float)):
            if isinstance(candidate,float) and not math.isfinite(candidate):
                snapshot.reject('material attribute input is not finite',name)
            return candidate
        # These are the only aggregate values the fixed runtime's Attribute
        # lookup exports. Strings, IDs and property groups produce no input.
        if isinstance(candidate,(str,bytes)) or isinstance(candidate,bpy.types.bpy_struct):return None
        try:
            if not 1<=len(candidate)<=4:return None
            result=list(candidate)
        except TypeError:return None
        if not all(isinstance(v,(bool,int,float)) for v in result):return None
        if any(isinstance(v,float) and not math.isfinite(v) for v in result):
            snapshot.reject('material attribute vector is not finite',name)
        return result
    scene=bpy.context.scene
    # Instancer mode can use a non-mesh parent/collection/GN instance owner.
    # Bind all reconstructed object candidates once rather than guessing the
    # current evaluated instance chain or copying an O(objects**2) witness.
    owners=[('scene',scene),('world',scene.world)]
    for obj in sorted(bpy.data.objects,key=lambda o:o.name):
        owners.append(('object:'+obj.name,obj))
        if obj.data is not None:owners.append(('data:'+obj.name,obj.data))
    owners += [('viewLayer:'+layer.name,layer) for layer in scene.view_layers]
    return {label:{name:value(owner,name) for name in sorted(names)}
            for label,owner in owners if owner is not None}
