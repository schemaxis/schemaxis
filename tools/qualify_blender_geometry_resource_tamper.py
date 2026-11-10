"""Resolved pointers and part-modifier ownership reject refreshed native edits."""
import argparse,json
from pathlib import Path
from blender_tamper import qualify

def main():
 p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();reports=[]
 reports.append(qualify(a.blender,[('object',a.suite/'object-RELATIVE-False')],{
  'objectPointer':"bpy.data.node_groups['copy'].nodes['source'].inputs['Object'].default_value=bpy.data.objects['target']",
  'coordinateSpace':"bpy.data.node_groups['copy'].nodes['source'].transform_space='ORIGINAL'",
  'instancePolicy':"bpy.data.node_groups['copy'].nodes['source'].inputs['As Instance'].default_value=True",
  'sourceGeometry':"bpy.data.objects['source'].data.vertices[1].co.x+=.4",
  'disabledBinding':"bpy.data.objects['target'].modifiers['schemaxis-geometry-copy'].show_render=False"}))
 reports.append(qualify(a.blender,[('collection',a.suite/'collection-ORIGINAL-True-True')],{
  'collectionPointer':"c=bpy.data.collections.new('replacement');bpy.context.scene.collection.children.link(c);bpy.data.node_groups['copy'].nodes['source'].inputs['Collection'].default_value=c",
  'childPlacementPolicy':"bpy.data.node_groups['copy'].nodes['source'].inputs['Reset Children'].default_value=False"}))
 reports.append(qualify(a.blender,[('group',a.suite/'group-resource-input')],{
  'groupPointerOverride':"bpy.data.node_groups['copy'].nodes['nested'].inputs['prototype'].default_value=bpy.data.objects['target']",
  'groupPointerDefault':"s=next(s for s in bpy.data.node_groups['reuse'].interface.items_tree if s.item_type=='SOCKET' and s.name=='prototype');s.default_value=bpy.data.objects['target']"}))
 reports.append(qualify(a.blender,[('asset',a.assets/'native-part-modifier')],{
  'prototypeModifierRemoved':"o=bpy.data.objects['assembly--prototype'];o.modifiers.remove(o.modifiers['schemaxis-geometry-lift'])",
  'collectionOffset':"c=next(c for c in bpy.data.collections if c.name.endswith('Parts'));c.instance_offset.x+=.2",
  'wholeAssetPointer':"bpy.data.node_groups['copy'].nodes['source'].inputs['Collection'].default_value=bpy.data.objects['assembly'].instance_collection"}))
 output={'status':'passed','cases':[c for r in reports for c in r['cases']],'controls':[c for r in reports for c in r['controls']]};a.output.write_text(json.dumps(output,indent=2)+'\n');print(json.dumps({'status':'passed','mutations':len(output['cases']),'unchangedSaveControls':len(output['controls'])}))

if __name__=='__main__':main()
