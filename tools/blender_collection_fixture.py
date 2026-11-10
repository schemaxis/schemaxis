"""Native-only deterministic collection asset fixture for the public qualifier."""
import argparse
import math
from pathlib import Path
import sys
import bpy


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene;scene.name='Assembly';scene.view_layers[0].name='Main';scene.frame_end=11
    container=bpy.data.collections.new('Container');scene.collection.children.link(container)
    visible=bpy.data.collections.new('Visible');container.children.link(visible)
    shared=bpy.data.collections.new('SharedMembership');scene.collection.children.link(shared)
    excluded=bpy.data.collections.new('Excluded');container.children.link(excluded)
    prototype=bpy.data.collections.new('Prototype');sub=bpy.data.collections.new('Subassembly');prototype.children.link(sub)
    nested=bpy.data.collections.new('NestedPrototype')
    bpy.ops.mesh.primitive_cube_add();temporary=bpy.context.object;mesh=temporary.data;mesh.name='SharedCube';bpy.data.objects.remove(temporary,do_unlink=True)
    material=bpy.data.materials.new('Blue');material.diffuse_color=(.05,.2,.8,1);mesh.materials.append(material)
    def cube(name,collection,location):
        obj=bpy.data.objects.new(name,mesh);collection.objects.link(obj);obj.location=location;return obj
    cube('PrototypeCube',prototype,(0,0,0));nested_cube=cube('NestedCube',nested,(0,3,0))
    inner=bpy.data.objects.new('NestedInstance',None);sub.objects.link(inner);inner.instance_type='COLLECTION';inner.instance_collection=nested
    root=bpy.data.objects.new('AssemblyRoot',None);visible.objects.link(root)
    target=bpy.data.objects.new('ConstraintTarget',None);target.location=(0,40,50);target.use_fake_user=True
    constraint=root.constraints.new('COPY_LOCATION');constraint.target=target;constraint.use_y=False;constraint.use_z=False
    for name,location,angle in [('FirstInstance',(10,0,0),0),('SecondInstance',(0,10,0),math.pi/2)]:
        obj=bpy.data.objects.new(name,None);visible.objects.link(obj);obj.instance_type='COLLECTION';obj.instance_collection=prototype;obj.location=location;obj.rotation_euler.z=angle;obj.parent=root
    loose=cube('LooseShared',visible,(0,0,0));loose.parent=root;shared.objects.link(loose)
    cube('ExcludedCube',excluded,(1000,1000,0))
    scene.view_layers['Main'].layer_collection.children['Container'].children['Excluded'].exclude=True;scene.view_layers.new('All')
    next(edge for c,edge in zip(container.children,container.collection_children) if c==visible).light_linking.link_state='EXCLUDE'
    for frame,value in [(1,0),(11,2)]:root.location.y=value;root.keyframe_insert('location',frame=frame)
    for layer in root.animation_data.action.layers:
        for strip in layer.strips:
            for curve in strip.channelbag(root.animation_data.action_slot).fcurves:
                for key in curve.keyframe_points:key.interpolation='LINEAR'
    other=bpy.data.scenes.new('Other');cube('OtherCube',other.collection,(-100,0,0))
    scene.frame_set(6);bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out/'source.blend'))
    varied=mesh.copy();varied.name='TallCube'
    for vertex in varied.vertices:vertex.co.z*=2
    nested_cube.data=varied;bpy.ops.wm.save_as_mainfile(filepath=str(out/'variants.blend'));nested_cube.data=mesh
    prototype.instance_offset=(1,0,0);bpy.ops.wm.save_as_mainfile(filepath=str(out/'offset.blend'));prototype.instance_offset=(0,0,0)
    target.name='model';bpy.ops.wm.save_as_mainfile(filepath=str(out/'dependency-name-collision.blend'));target.name='ConstraintTarget'
    # Additional explicit loss/ambiguity cases keep the same useful geometry.
    scene.view_layers['Main'].material_override=material;bpy.ops.wm.save_as_mainfile(filepath=str(out/'override.blend'));scene.view_layers['Main'].material_override=None
    scene.view_layers['Main'].layer_collection.children['Container'].children['Visible'].holdout=True;bpy.ops.wm.save_as_mainfile(filepath=str(out/'holdout.blend'));scene.view_layers['Main'].layer_collection.children['Container'].children['Visible'].holdout=False
    scene.view_layers['Main'].layer_collection.children['Container'].children['Visible'].hide_viewport=True;bpy.ops.wm.save_as_mainfile(filepath=str(out/'local-hidden.blend'));scene.view_layers['Main'].layer_collection.children['Container'].children['Visible'].hide_viewport=False
    # Plain libraries without scenes retain the legacy unambiguous object route.
    plain=cube('LibraryCube',scene.collection,(0,0,0));bpy.data.libraries.write(str(out/'objects.blend'),{plain})
    bpy.data.libraries.write(str(out/'collection-library.blend'),{inner})

if __name__=='__main__':main()
