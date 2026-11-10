"""One managed unlinked preview image, independent of the material shader.

An active empty image node deliberately selects the material swatch fallback.
Merely clearing the active node or image flags leaves Blender's image fallback.
"""
from schemaxis.errors import fail

NAME='__schemaxis_display_texture'


def build(tree,spec,images):
    node=tree.nodes.new('ShaderNodeTexImage');node.name=NAME
    node.label='Display texture';node.location=(0,-300)
    node.image=images[spec['image']] if spec['kind']=='image' else None
    node.interpolation='Linear';node.extension='REPEAT';node.projection='FLAT'
    for other in tree.nodes:
        if other.bl_idname=='ShaderNodeTexImage':other.show_texture=False
    tree.nodes.active=node;node.show_texture=True


def observe(tree):
    node=tree.nodes.get(NAME)
    if (node is None or node.bl_idname!='ShaderNodeTexImage' or node.mute
            or not node.show_texture or node.interpolation!='Linear'
            or node.extension!='REPEAT' or node.projection!='FLAT'
            or any(s.is_linked for s in [*node.inputs,*node.outputs])):
        fail('VERIFICATION_FAILED','material display texture helper differs',tree.name)
    if any(n!=node and n.bl_idname=='ShaderNodeTexImage' and n.show_texture for n in tree.nodes):
        fail('VERIFICATION_FAILED','undeclared active material display texture',tree.name)
    return {'kind':'image','image':node.image.name} if node.image else {'kind':'none'}
