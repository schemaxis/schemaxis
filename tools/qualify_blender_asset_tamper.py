"""Prove imported editable state survives save/reopen and rejects changed bytes."""
import argparse
import json
from pathlib import Path
from blender_tamper import qualify

MUTATIONS = {
    'materialRoughness': """
material=next(m for m in bpy.data.materials if m.name.startswith('ceramic'))
node=next(n for n in material.node_tree.nodes if n.bl_idname=='ShaderNodeBsdfPrincipled')
node.inputs['Roughness'].default_value += .123
""",
    'unsampledAnimationKey': """
obj=bpy.data.objects['product--motion']
action=obj.animation_data.action
curve=next(c for layer in action.layers for strip in layer.strips for c in strip.channelbag(obj.animation_data.action_slot).fcurves if c.data_path=='location' and c.array_index==0)
for frame,value in [(6,2),(7,10),(8,2.8)]:
 key=curve.keyframe_points.insert(frame,value)
 key.interpolation='LINEAR'
curve.update()
""",
    'uvCoordinate': """
obj=bpy.data.objects['product--box']
obj.data.uv_layers.active.data[0].uv.x += .125
""",
    'skinWeight': """
obj=bpy.data.objects['product--box']
obj.vertex_groups['root'].add([0],.5,'REPLACE')
""",
}


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--run',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=qualify(a.blender,[('reused',Path(a.run))],MUTATIONS,'')
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','mutations':len(report['cases']),'unchangedSaveControls':len(report['controls'])}))

if __name__=='__main__':main()
