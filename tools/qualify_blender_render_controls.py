"""Saved native render-control changes with refreshed hashes and save controls."""
import argparse,json
from pathlib import Path
from blender_tamper import qualify


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.suite.absolute();records=[]
    cases=[('cycles-exposure-0',{
        'engine':"bpy.context.scene.render.engine='BLENDER_WORKBENCH'",
        'view':"bpy.context.scene.view_settings.view_transform='Raw'",
        'outputColourOverride':"s=bpy.context.scene.render.image_settings;s.color_management='OVERRIDE';s.view_settings.view_transform='Standard';s.view_settings.exposure=1",
        'exposure':"bpy.context.scene.view_settings.exposure=1",
        'gamma':"bpy.context.scene.view_settings.gamma=1.2",
        'whiteBalance':"bpy.context.scene.view_settings.use_white_balance=True",
        'worldConnection':"t=bpy.context.scene.world.node_tree;t.links.remove(t.links[0])",
        'worldOutputTarget':"bpy.context.scene.world.node_tree.nodes['World Output'].target='EEVEE'",
        'lampDirection':"bpy.data.objects['__schemaxis_light'].rotation_euler.z+=.4",
        'lampEmission':"bpy.data.objects['__schemaxis_light'].data.node_tree.nodes['Emission'].inputs['Strength'].default_value=2",
        'dagMaterialConnection':"t=bpy.data.materials['SXProductionMaterial'].node_tree;t.links.remove(t.links[0])",
        'dagUndeclaredNormal':"bpy.data.materials['SXProductionMaterial'].node_tree.nodes['Principled BSDF'].inputs['Normal'].default_value=(1,0,0)",
        'materialViewportColour':"bpy.data.materials['surface'].diffuse_color[0]=.8",
        'objectDisplayColour':"bpy.data.objects['patch'].color[0]=.8"}),
      ('eevee-exposure-0',{'rayTracing':"bpy.context.scene.eevee.use_raytracing=True",'inactiveGIThreshold':"bpy.context.scene.eevee.ray_tracing_options.trace_max_roughness=.75"}),
      ('workbench-object-colour',{'surfaceMode':"bpy.context.scene.display.shading.type='WIREFRAME'"}),
      ('workbench-attribute-colour',{'activeColour':"bpy.data.objects['patch'].data.color_attributes.active_color_index=0",'renderColour':"bpy.data.objects['patch'].data.color_attributes.render_color_index=0"}),
      ('workbench-instance-display-colours',{'inheritedDisplayColour':"bpy.data.objects['inherited'].color[1]=.9"}),
      ('view-agx',{'contrastLook':"bpy.context.scene.view_settings.look='AgX - Punchy'"})]
    for label,mutations in cases:records.append(qualify(a.blender,[(label,root/label)],mutations))
    report={'status':'passed','cases':[r for record in records for r in record['cases']],'controls':[r for record in records for r in record['controls']]};a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','mutations':len(report['cases']),'controls':len(report['controls'])}))

if __name__=='__main__':main()
