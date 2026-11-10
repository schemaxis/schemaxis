"""Refreshed-hash attacks against authored and imported native motion intent."""
import argparse
import json
from pathlib import Path
from blender_tamper import qualify

MUTATIONS={
 'unsampledStripInfluence':"""
obj=next(o for o in bpy.data.objects if o.type=='MESH' and o.animation_data and len(o.animation_data.nla_tracks)>1)
strip=obj.animation_data.nla_tracks[1].strips[0]
curve=strip.fcurves[0]
for frame,value in [(6,.5),(7,.9),(8,.5)]:
 p=curve.keyframe_points.insert(frame,value);p.interpolation='LINEAR'
curve.update()
""",
 'nestedActionKey':"""
obj=next(o for o in bpy.data.objects if o.type=='MESH' and o.animation_data and len(o.animation_data.nla_tracks)>1)
strip=obj.animation_data.nla_tracks[1].strips[0]
curve=next(c for layer in strip.action.layers for section in layer.strips for c in section.channelbag(strip.action_slot).fcurves if c.data_path=='location' and c.array_index==0)
for frame,value in [(6,2),(7,12),(8,2.8)]:
 p=curve.keyframe_points.insert(frame,value);p.interpolation='LINEAR'
curve.update()
""",
 'unsampledInteriorInterpolation':"""
obj=next(o for o in bpy.data.objects if o.type=='MESH' and o.animation_data and len(o.animation_data.nla_tracks)>1)
strip=obj.animation_data.nla_tracks[1].strips[0]
curves=[c for layer in strip.action.layers for section in layer.strips for c in section.channelbag(strip.action_slot).fcurves if c.data_path=='location']
assert len(curves)==3
for curve in curves:
 point=next(p for p in curve.keyframe_points if p.co.x==3)
 point.interpolation='CONSTANT'
""",
 'morphCoordinate':"""
obj=next(o for o in bpy.data.objects if o.type=='MESH' and o.data.shape_keys and o.data.shape_keys.use_relative)
obj.data.shape_keys.key_blocks['lift'].data[2].co.z += .5
""",
 'orderedTrackSwap':"""
obj=next(o for o in bpy.data.objects if o.type=='MESH' and o.animation_data and len(o.animation_data.nla_tracks)>1)
obj.animation_data.nla_tracks[0].mute=True
""",
}


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--project',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=qualify(a.blender,[(case,Path(a.project)/case) for case in ('connected','reused')],MUTATIONS,'')
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','mutations':len(report['cases']),'unchangedSaveControls':len(report['controls'])}))

if __name__=='__main__':main()
