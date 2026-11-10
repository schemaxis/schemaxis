"""Refreshed-hash current-byte attacks against reusable group intent."""
import argparse
import json
from pathlib import Path
from blender_tamper import qualify

MUTATIONS={
 'interfaceObjectReference':"""
anchor=next(o for o in bpy.data.objects if o.name=='anchor' or o.name.endswith('--anchor'))
other=next(o for o in bpy.data.objects if o.name=='otherAnchor' or o.name.endswith('--otherAnchor'))
bpy.data.node_groups['Lift'].interface.items_tree['referenceObject'].default_value=other
for tree in bpy.data.node_groups:
 for node in tree.nodes:
  if node.bl_idname=='GeometryNodeGroup' and node.node_tree and node.node_tree.name=='Lift':node.inputs['referenceObject'].default_value=anchor
""",
 'interfaceDefault':"bpy.data.node_groups['Surface'].interface.items_tree['roughness'].default_value=.7",
 'nestedLinkedFallback':"bpy.data.node_groups['LiftTwice'].nodes['first'].inputs['lift'].default_value=(0,0,123)",
 'interfaceBounds':"bpy.data.node_groups['Surface'].interface.items_tree['roughness'].max_value=.9",
 'nestedNodeMute':"bpy.data.node_groups['LiftTwice'].nodes['first'].mute=True",
 'groupBinding':"bpy.data.node_groups['lifted'].nodes['lift'].node_tree=bpy.data.node_groups['Lift']",
}


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--project',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=qualify(a.blender,[(case,Path(a.project)/case) for case in ('connected','reused')],MUTATIONS,'')
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','mutations':len(report['cases']),'unchangedSaveControls':len(report['controls'])}))

if __name__=='__main__':main()
