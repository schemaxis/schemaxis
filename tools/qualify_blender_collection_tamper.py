"""Current-byte native attacks on owned collection identity and dependencies."""
import argparse
import json
from pathlib import Path
from blender_tamper import qualify

MUTATIONS={
 'objectMembership':"c=next(c for c in loose.users_collection if c.name=='Visible');c.objects.unlink(loose)",
 'sharedDataIdentity':"loose.data=loose.data.copy()",
 'instanceCollectionIdentity':"first.instance_collection=first.instance_collection.copy()",
 'nestedCollectionMembership':"c=first.instance_collection;c.children.unlink(next(iter(c.children)))",
 'collectionOffset':"first.instance_collection.instance_offset.y=.2",
 'collectionLinkPolicy':"c=first.instance_collection;next(iter(c.collection_children)).light_linking.link_state='EXCLUDE'",
 'fullActionCurves':"root=first.parent;root.location.y=.4;root.keyframe_insert('location',frame=3)",
 'objectMaterialOverride':"m=loose.material_slots[0].material;loose.material_slots[0].link='OBJECT';loose.material_slots[0].material=m.copy()",
 'unsampledMesh':"loose.data.vertices[0].co.x-=.05",
 'nonvisibleDependency':"first.parent.constraints[0].target.location.y=41",
 'excludedProjection':"import json;s=json.loads(asset['schemaxisAssetSelection']);s['excluded']=[] if s['excluded'] else [['Injected']];asset['schemaxisAssetSelection']=json.dumps(s)",
 'selectedLayer':"import json;s=json.loads(asset['schemaxisAssetSelection']);s['viewLayer']='All';asset['schemaxisAssetSelection']=json.dumps(s)",
}


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--project',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    report=qualify(a.blender,[(case,Path(a.project)/case) for case in ('main','reused')],MUTATIONS,"asset=bpy.data.objects['model'];loose=next(o for o in bpy.data.objects if o.name.endswith('--LooseShared'));first=next(o for o in bpy.data.objects if o.name.endswith('--FirstInstance'))")
    Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','mutations':len(report['cases']),'unchangedSaveControls':len(report['controls'])}))

if __name__=='__main__':main()
