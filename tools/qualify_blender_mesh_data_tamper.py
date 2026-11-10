"""Current native bytes reject field/UV/ownership changes; no-op saves pass."""
import argparse
import json
from pathlib import Path
from blender_tamper import qualify


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',required=True);p.add_argument('--output',required=True);a=p.parse_args();suite=Path(a.suite);reports=[]
    fields={
        'scientificScalar':"bpy.data.objects['panel'].data.attributes['temperature'].data[2].value+=7",
        'vectorField':"bpy.data.objects['panel'].data.attributes['displacement'].data[1].vector.z+=.25",
        'linearColour':"bpy.data.objects['panel'].data.attributes['fieldColour'].data[0].color=(.2,.3,.4,1)",
        'namedCoordinate':"bpy.data.objects['panel'].data.uv_layers['Label'].data[0].uv.x+=.125",
        'packedCoordinate':"bpy.data.objects['panel'].data.uv_layers['Atlas'].data[0].uv.y+=.02",
        'activeUV':"bpy.data.objects['panel'].data.uv_layers.active=bpy.data.objects['panel'].data.uv_layers['Atlas']",
        'renderUV':"bpy.data.objects['panel'].data.uv_layers['Atlas'].active_render=True",
        'shaderFieldBinding':"bpy.data.materials['fieldColour'].node_tree.nodes['colour'].attribute_name='temperature'",
        'typedFieldReader':"bpy.data.node_groups['deform'].nodes['field'].data_type='FLOAT'",
    }
    reports.append(qualify(a.blender,[('authored',suite/'fields')],fields))
    typed={
        'byteColour':"v=bpy.data.objects['panel'].data.attributes['byteColourPOINTconstant'].data[0];v.color_srgb=(.8,.3,.2,1)",
        'quaternion':"bpy.data.objects['panel'].data.attributes['quaternionFACEconstant'].data[0].value=(1,0,0,0)",
        'edgeDomain':"bpy.data.objects['panel'].data.attributes['integerEDGEconstant'].data[0].value+=1",
        'cornerVector':"bpy.data.objects['panel'].data.attributes['vectorCORNERsparse'].data[0].vector.x+=.5",
    }
    reports.append(qualify(a.blender,[('typed',suite/'types-domains-storage')],typed))
    reports.append(qualify(a.blender,[('seams',suite/'unwrap-conformal')],{'seamEndpoint':"e=next(e for e in bpy.data.objects['panel'].data.edges if e.use_seam);e.use_seam=False"}))
    reports.append(qualify(a.blender,[('copy',suite/'sharing-copy')],{'copyOwnership':"bpy.data.objects['panel'].data=bpy.data.objects['twin'].data"}))
    reports.append(qualify(a.blender,[('shared',suite/'sharing-shared')],{'sharedOwnership':"bpy.data.objects['twin'].data=bpy.data.objects['twin'].data.copy()"}))
    reports.append(qualify(a.blender,[('collection-copy',suite/'collection-source-copy')],{
        'selectedPrototypeSharing':"bpy.data.objects['assembly--partA'].data=bpy.data.objects['assembly--partB'].data",
        'unselectedPrototypeSource':"bpy.data.objects['assembly--partB'].data.vertices[1].co.x+=.3",
    }))
    output={'status':'passed','cases':[c for r in reports for c in r['cases']],'controls':[c for r in reports for c in r['controls']]}
    Path(a.output).write_text(json.dumps(output,indent=2)+'\n');print(json.dumps({'status':'passed','mutations':len(output['cases']),'unchangedSaveControls':len(output['controls'])}))

if __name__=='__main__':main()
