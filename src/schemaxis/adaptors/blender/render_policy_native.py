"""Native mapping/readback for the finite rendering and display policies."""
import os
from pathlib import Path
import bpy
from schemaxis.errors import fail
from .render_policy import AGX_LOOKS,VIEWS
from .settings import matching

ENGINES={'cycles':'CYCLES','eevee':'BLENDER_EEVEE','workbench':'BLENDER_WORKBENCH'}
SOURCES={'material':'MATERIAL','object':'OBJECT','random':'RANDOM','attribute':'VERTEX','single':'SINGLE','texture':'TEXTURE'}


def _inverse(mapping,value,where):
    for key,native in mapping.items():
        if value==native:return key
    fail('VERIFICATION_FAILED','native setting is outside the declared policy',where,value=value)


def _builtin(preset,kind):
    light=bpy.context.preferences.studio_lights.get(preset)
    root=Path(bpy.utils.resource_path('LOCAL'))/'datafiles'/'studiolights'/('studio' if kind=='studio' else 'matcap')
    if not light or light.type!=('STUDIO' if kind=='studio' else 'MATCAP') or Path(light.path).resolve()!=(root/preset).resolve() or not (root/preset).is_file():
        fail('UNSUPPORTED_RESOURCE','declared bundled lighting preset is unavailable or overridden','render.renderer.lighting.preset',preset=preset)


def configure(scene,settings):
    bundled=Path(bpy.utils.resource_path('LOCAL'))/'datafiles'/'colormanagement'/'config.ocio'
    # Blender itself populates OCIO with its bundled configuration on startup.
    if os.environ.get('OCIO') and Path(os.environ['OCIO']).resolve()!=bundled.resolve():fail('UNSUPPORTED_RESOURCE','custom OCIO configuration needs an explicitly captured colour workflow','render.colourManagement')
    renderer=settings['renderer'];kind=renderer['kind'];scene.render.engine=ENGINES[kind]
    if kind=='cycles':
        osl=renderer.get('shadingSystem')=='osl'
        if osl and not bpy.app.build_options.cycles_osl:
            fail('UNSUPPORTED_SHADER_BACKEND','configured Blender runtime lacks built-in OSL support','render.renderer.shadingSystem')
        scene.cycles.shading_system=osl
    colour=settings['colourManagement'];view=scene.view_settings
    scene.display_settings.display_device='sRGB'
    view.view_transform=VIEWS[colour['view']['kind']]
    view.look=AGX_LOOKS[colour['view']['contrast']] if colour['view']['kind']=='agx' else 'None'
    view.exposure=colour['exposure'];view.gamma=colour['gamma'];view.use_curve_mapping=False
    balance=colour['whiteBalance'];view.use_white_balance=balance['kind']=='on'
    if balance['kind']=='on':view.white_balance_temperature=balance['temperature'];view.white_balance_tint=balance['tint']
    scene.render.dither_intensity=0
    scene.render.image_settings.color_mode='RGBA';scene.render.image_settings.color_depth='8'
    scene.render.image_settings.color_management='FOLLOW_SCENE'
    if kind=='eevee':
        e=scene.eevee;e.taa_render_samples=renderer['samples'];e.shadow_ray_count=renderer['shadowRays'];e.shadow_step_count=renderer['shadowSteps']
        ray=renderer['rayTracing'];e.use_raytracing=ray['kind']!='off';e.ray_tracing_method='SCREEN'
        if ray['kind']=='screen':
            t=e.ray_tracing_options;t.resolution_scale=ray['resolution'];t.screen_trace_quality=ray['quality'];t.screen_trace_thickness=ray['thickness']
            t.use_backface_hit=ray['backfaces']['kind']=='bothSides'
            if t.use_backface_hit:t.backface_radiance_scale=ray['backfaces']['radianceReuse']
            d=ray['denoise'];t.use_denoise=d['kind']=='filtered'
            if d['kind']=='filtered':t.denoise_spatial=d['spatial'];t.denoise_temporal=d['temporal'];t.denoise_bilateral=d['bilateral']
        gi=renderer['fastGI'];e.use_fast_gi=gi['kind']!='off'
        e.ray_tracing_options.trace_max_roughness=gi.get('roughnessThreshold',1)
        if gi['kind']!='off':
            e.fast_gi_method='GLOBAL_ILLUMINATION' if gi['kind']=='global' else 'AMBIENT_OCCLUSION_ONLY'
            e.fast_gi_resolution=gi['resolution'];e.fast_gi_quality=gi['quality'];e.fast_gi_ray_count=gi['rays'];e.fast_gi_step_count=gi['steps']
            e.fast_gi_distance=gi['distance'];e.fast_gi_thickness_near=gi['thickness'];e.fast_gi_bias=gi['bias']
    elif kind=='workbench':
        d=scene.display;s=d.shading;s.type='SOLID';l=renderer['lighting'];s.light=l['kind'].upper()
        if l['kind']!='flat':
            _builtin(l['preset'],l['kind']);s.studio_light=l['preset'];s.show_specular_highlight=l.get('specular',False)
            if l['kind']=='studio':s.use_world_space_lighting=l['worldSpace'];s.studiolight_rotate_z=l['rotation']
        source=renderer['colourSource'];s.color_type=SOURCES[source['kind']]
        if source['kind']=='single':s.single_color=source['colour']
        s.background_type='VIEWPORT';s.background_color=renderer['background'];d.render_aa=renderer['antiAliasing']
        shadow=renderer['shadows'];s.show_shadows=shadow['kind']=='on'
        if shadow['kind']=='on':d.light_direction=shadow['direction'];s.shadow_intensity=shadow['darkness'];d.shadow_shift=shadow['shift'];d.shadow_focus=shadow['focus']
        cavity=renderer['cavity'];s.show_cavity=cavity['kind']!='off'
        if cavity['kind']!='off':
            s.cavity_type=cavity['kind'].upper()
            if cavity['kind'] in ('world','both'):s.cavity_ridge_factor=cavity.get('worldRidge',cavity.get('ridge'));s.cavity_valley_factor=cavity.get('worldValley',cavity.get('valley'))
            if cavity['kind'] in ('screen','both'):s.curvature_ridge_factor=cavity.get('screenRidge',cavity.get('ridge'));s.curvature_valley_factor=cavity.get('screenValley',cavity.get('valley'))
        outline=renderer['outline'];s.show_object_outline=outline['kind']=='on'
        if outline['kind']=='on':s.object_outline_color=outline['colour']
        xray=renderer['xray'];s.show_xray=xray['kind']=='on'
        if xray['kind']=='on':s.xray_alpha=xray['alpha']
        s.show_backface_culling=renderer['backfaceCulling']


def observe(scene):
    kind=_inverse(ENGINES,scene.render.engine,'render.renderer');renderer={'kind':kind}
    if kind=='cycles' and scene.cycles.shading_system:renderer['shadingSystem']='osl'
    view=scene.view_settings;vkind=_inverse(VIEWS,view.view_transform,'render.colourManagement.view');transform={'kind':vkind}
    if vkind=='agx':transform['contrast']=_inverse(AGX_LOOKS,view.look,'render.colourManagement.view.contrast')
    elif view.look!='None':fail('VERIFICATION_FAILED','undeclared display look','render.colourManagement.view')
    if scene.display_settings.display_device!='sRGB' or view.use_curve_mapping or scene.render.dither_intensity!=0 or scene.render.image_settings.color_mode!='RGBA' or scene.render.image_settings.color_depth!='8' or scene.render.image_settings.color_management!='FOLLOW_SCENE':
        fail('VERIFICATION_FAILED','undeclared display/output processing','render.colourManagement')
    if scene.animation_data:fail('VERIFICATION_FAILED','undeclared render settings animation','render')
    balance={'kind':'on','temperature':view.white_balance_temperature,'tint':view.white_balance_tint} if view.use_white_balance else {'kind':'off'}
    colour={'view':transform,'exposure':view.exposure,'gamma':view.gamma,'whiteBalance':balance}
    if kind=='eevee':
        e=scene.eevee;ray={'kind':'off'}
        if e.use_raytracing:
            if e.ray_tracing_method!='SCREEN':fail('VERIFICATION_FAILED','ray tracing method changed','render.renderer.rayTracing')
            t=e.ray_tracing_options
            denoise={'kind':'filtered','spatial':t.denoise_spatial,'temporal':t.denoise_temporal,'bilateral':t.denoise_bilateral} if t.use_denoise else {'kind':'none'}
            backfaces={'kind':'bothSides','radianceReuse':t.backface_radiance_scale} if t.use_backface_hit else {'kind':'singleSided'}
            ray={'kind':'screen','resolution':t.resolution_scale,'quality':t.screen_trace_quality,'thickness':t.screen_trace_thickness,'denoise':denoise,'backfaces':backfaces}
        gi={'kind':'off'}
        if e.use_fast_gi:
            gkind=_inverse({'ambient':'AMBIENT_OCCLUSION_ONLY','global':'GLOBAL_ILLUMINATION'},e.fast_gi_method,'render.renderer.fastGI')
            gi={'kind':gkind,'resolution':e.fast_gi_resolution,'quality':e.fast_gi_quality,'rays':e.fast_gi_ray_count,'steps':e.fast_gi_step_count,'roughnessThreshold':e.ray_tracing_options.trace_max_roughness,'distance':e.fast_gi_distance,'thickness':e.fast_gi_thickness_near,'bias':e.fast_gi_bias}
        elif e.ray_tracing_options.trace_max_roughness!=1:fail('VERIFICATION_FAILED','disabled GI roughness threshold changed','render.renderer.fastGI')
        renderer.update(samples=e.taa_render_samples,rayTracing=ray,fastGI=gi,shadowRays=e.shadow_ray_count,shadowSteps=e.shadow_step_count)
    elif kind=='workbench':
        if scene.display.shading.type!='SOLID':fail('VERIFICATION_FAILED','technical surface shading mode changed','render.renderer')
        d=scene.display;s=d.shading;lkind=_inverse({'flat':'FLAT','studio':'STUDIO','matcap':'MATCAP'},s.light,'render.renderer.lighting');lighting={'kind':lkind}
        if lkind!='flat':
            _builtin(s.studio_light,lkind);lighting.update(preset=s.studio_light)
            if lkind=='studio':lighting.update(worldSpace=s.use_world_space_lighting,rotation=s.studiolight_rotate_z,specular=s.show_specular_highlight)
        source={'kind':_inverse(SOURCES,s.color_type,'render.renderer.colourSource')}
        if source['kind']=='single':source['colour']=list(s.single_color)
        if s.background_type!='VIEWPORT':fail('VERIFICATION_FAILED','technical background source changed','render.renderer.background')
        shadows={'kind':'on','direction':list(d.light_direction),'darkness':s.shadow_intensity,'shift':d.shadow_shift,'focus':d.shadow_focus} if s.show_shadows else {'kind':'off'}
        cavity={'kind':'off'}
        if s.show_cavity:
            ckind=_inverse({'world':'WORLD','screen':'SCREEN','both':'BOTH'},s.cavity_type,'render.renderer.cavity');cavity={'kind':ckind}
            if ckind=='world':cavity.update(ridge=s.cavity_ridge_factor,valley=s.cavity_valley_factor)
            elif ckind=='screen':cavity.update(ridge=s.curvature_ridge_factor,valley=s.curvature_valley_factor)
            else:cavity.update(worldRidge=s.cavity_ridge_factor,worldValley=s.cavity_valley_factor,screenRidge=s.curvature_ridge_factor,screenValley=s.curvature_valley_factor)
        renderer.update(lighting=lighting,colourSource=source,background=list(s.background_color),antiAliasing=d.render_aa,shadows=shadows,cavity=cavity,
            outline={'kind':'on','colour':list(s.object_outline_color)} if s.show_object_outline else {'kind':'off'},xray={'kind':'on','alpha':s.xray_alpha} if s.show_xray else {'kind':'off'},backfaceCulling=s.show_backface_culling)
    return {'renderer':renderer,'colourManagement':colour}


def verify_light_tree(light):
    """Typed lamp colour/energy multiply the native default emission graph."""
    tree=light.node_tree
    if not tree or tree.animation_data:fail('VERIFICATION_FAILED','light emission graph changed',light.name)
    emission=tree.nodes.get('Emission');output=tree.nodes.get('Light Output')
    if not emission or not output or len(tree.nodes)!=2 or len(tree.links)!=1 or emission.bl_idname!='ShaderNodeEmission' or output.bl_idname!='ShaderNodeOutputLight' or emission.mute or output.mute or not output.is_active_output or output.target!='ALL':
        fail('VERIFICATION_FAILED','light emission graph membership changed',light.name)
    link=tree.links[0]
    if link.is_muted or link.from_node!=emission or link.to_node!=output or link.from_socket!=emission.outputs['Emission'] or link.to_socket!=output.inputs['Surface'] or not matching(list(emission.inputs['Color'].default_value),[1,1,1,1]) or emission.inputs['Strength'].default_value!=1:
        fail('VERIFICATION_FAILED','light emission graph values/connections changed',light.name)


def verify_material_tree(material,authored_sockets,features=None):
    """Bind the DAG material's finite Principled shader and native defaults."""
    tree=material.node_tree
    if not material.use_nodes or not tree or material.animation_data or tree.animation_data:
        fail('VERIFICATION_FAILED','DAG material shading changed',material.name)
    counts=features.verify_auxiliary(material) if features is not None else (0,0)
    auxiliary={n['id'] for part in features.auxiliary(material) for n in part['nodes']} if features is not None else set()
    shader=tree.nodes.get('Principled BSDF');output=tree.nodes.get('Material Output')
    if not shader or not output or len(tree.nodes)!=2+counts[0] or len(tree.links)!=1+counts[1] or shader.bl_idname!='ShaderNodeBsdfPrincipled' or output.bl_idname!='ShaderNodeOutputMaterial' or shader.mute or output.mute or not output.is_active_output or output.target!='ALL':
        fail('VERIFICATION_FAILED','DAG material graph membership changed',material.name)
    links=[link for link in tree.links if link.from_node.name not in auxiliary and link.to_node.name not in auxiliary]
    if len(links)!=1:fail('VERIFICATION_FAILED','DAG material base connection differs',material.name)
    link=links[0]
    if link.is_muted or link.from_node!=shader or link.to_node!=output or link.from_socket!=shader.outputs['BSDF'] or link.to_socket!=output.inputs['Surface']:
        fail('VERIFICATION_FAILED','DAG material connection changed',material.name)
    reference=bpy.data.materials.new('__schemaxis_material_reference')
    try:
        reference.use_nodes=True;default=reference.node_tree.nodes['Principled BSDF']
        if shader.distribution!=default.distribution or shader.subsurface_method!=default.subsurface_method:
            fail('VERIFICATION_FAILED','undeclared DAG shader model changed',material.name)
        def value(socket):
            v=socket.default_value
            return list(v) if hasattr(v,'__len__') else v
        for socket in default.inputs:
            if socket.name not in authored_sockets and hasattr(socket,'default_value'):
                actual=next((s for s in shader.inputs if s.identifier==socket.identifier),None)
                if actual is None or not matching(value(actual),value(socket)):
                    fail('VERIFICATION_FAILED','undeclared DAG shader input changed',material.name,socket=socket.name)
    finally:bpy.data.materials.remove(reference)
