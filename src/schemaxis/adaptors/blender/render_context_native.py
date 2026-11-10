"""Fresh finite renderer context, separate from editable readback witnesses.

Reflection reads only fixed reviewed native classes. No authored property path,
submitted settings object or persisted signature supplies this reference.
"""
import bpy
from schemaxis.errors import fail
from .asset_fidelity import matching
from .shader_fidelity_native import ShaderSnapshot

# Viewport-only sampling may change during inspection. Device authority is the
# existing typed render policy; trusted geometry reconstruction deliberately
# uses CPU even when the caller selected a separately evidenced GPU backend.
CYCLES_PRESENTATION={
    'name','device','preview_pause','preview_samples','use_preview_denoising',
    'preview_denoiser','preview_denoising_prefilter','preview_denoising_quality',
    'preview_denoising_input_passes','preview_denoising_start_sample',
    'preview_denoising_use_gpu','preview_scrambling_distance',
    'use_preview_adaptive_sampling','preview_adaptive_threshold',
    'preview_adaptive_min_samples','volume_preview_step_rate','preview_dicing_rate',
    'texture_resolution','texture_limit','ao_bounces',
}
RENDER_PRESENTATION={'filepath','use_lock_interface','preview_pixel_size','sequencer_gl_preview',
    'simplify_subdivision','simplify_child_particles','simplify_gpencil_onplay',
    'simplify_gpencil_view_fill','compositor_denoise_preview_quality'}
EEVEE_PRESENTATION={'taa_samples','use_taa_reprojection','use_shadow_jitter_viewport'}


def observe(features=None):
    scene=bpy.context.scene;reader=ShaderSnapshot([])
    def settings(value,kind,exclude=()):
        if value is None or value.bl_rna.identifier!=kind:
            fail('VERIFICATION_FAILED','renderer context requires a reviewed native settings class',kind)
        return reader.primitive(value,exclude=exclude)
    result={'version':'schemaxis.blender.render-context/1',
            'time':{'frame':scene.frame_current,'subframe':scene.frame_subframe},
            'gravity':{'enabled':scene.use_gravity,'vector':list(scene.gravity)},
            'cameraMarkers':sorted([{'frame':m.frame,'camera':m.camera.name}
                for m in scene.timeline_markers if m.camera is not None],
                key=lambda m:(m['frame'],m['camera'])),
            'render':settings(scene.render,'RenderSettings',RENDER_PRESENTATION),
            'image':settings(scene.render.image_settings,'ImageFormatSettings'),
            'view':settings(scene.view_settings,'ColorManagedViewSettings'),
            'display':settings(scene.display_settings,'ColorManagedDisplaySettings')}
    space=bpy.data.colorspace
    if space.bl_rna.identifier!='BlendFileColorspace':
        fail('VERIFICATION_FAILED','file colour interpretation needs its reviewed native class')
    # These read-only RNA values can change through the native working-space
    # operator without converting the stored shader colour values.
    result['workingColourSpace']={'space':space.working_space,
        'interop':space.working_space_interop_id,
        'missingConfiguration':space.is_missing_opencolorio_config}
    output=scene.render.image_settings
    result['outputView']=settings(output.view_settings,'ColorManagedViewSettings')
    result['outputDisplay']=settings(output.display_settings,'ColorManagedDisplaySettings')
    result['outputLinear']=settings(output.linear_colorspace_settings,'ColorManagedInputColorspaceSettings')
    # These non-scalar dependencies are inactive under the currently authored
    # policy. A changed enabling flag is itself source-bound below/above.
    if scene.render.use_multiview or scene.render.use_motion_blur or scene.view_settings.use_curve_mapping or output.view_settings.use_curve_mapping:
        fail('VERIFICATION_FAILED','stereo, motion-blur curves and display curves require a typed render context')
    # Native rendering/ordinary editor inspection can allocate an empty
    # sequencer. Any actual strip remains outside this typed scene contract.
    if scene.sequence_editor is not None and len(scene.sequence_editor.strips_all):
        fail('VERIFICATION_FAILED','a sequencer dependency requires a typed scene-rendering contract')
    camera=scene.camera
    if camera is None or camera.type!='CAMERA' or camera.library is not None:
        fail('VERIFICATION_FAILED','render camera requires a local native identity')
    result['camera']={'object':camera.name,'data':settings(camera.data,'Camera'),
                      'dof':settings(camera.data.dof,'CameraDOFSettings')}
    if camera.data.dof.use_dof or camera.data.dof.focus_object is not None:
        fail('VERIFICATION_FAILED','depth of field requires a typed camera contract')
    world=scene.world;lamp=bpy.data.objects.get('__schemaxis_light')
    if world is None or lamp is None or lamp.type!='LIGHT' or lamp.data.type!='AREA':
        fail('VERIFICATION_FAILED','render world and key light require their trusted native identities')
    result['world']={'name':world.name,'settings':settings(world,'World'),
                     'cycles':settings(world.cycles,'CyclesWorldSettings'),
                     'visibility':settings(world.cycles_visibility,'CyclesVisibilitySettings'),
                     'mist':settings(world.mist_settings,'WorldMistSettings'),
                     'lighting':settings(world.light_settings,'WorldLighting')}
    result['keyLight']={'name':lamp.name,'settings':settings(lamp.data,'AreaLight'),
                        'cycles':settings(lamp.data.cycles,'CyclesLightSettings')}
    from .render_members_native import observe as observe_members
    result['participation']=observe_members(features=features)
    kind=scene.render.engine
    if kind=='CYCLES':
        result['cycles']=settings(scene.cycles,'CyclesRenderSettings',CYCLES_PRESENTATION)
        # Fixed5.2.3 has one writable Cycles non-ID pointer. Refuse rather than
        # silently dropping any newly introduced dependency class.
        pointers={p.identifier for p in scene.cycles.bl_rna.properties if p.type in ('POINTER','COLLECTION') and p.identifier!='rna_type'}
        if pointers!={'dicing_camera'}:fail('VERIFICATION_FAILED','Cycles render dependencies require a reviewed mapping')
        camera=scene.cycles.dicing_camera
        if camera is not None:
            if camera.library is not None or camera.type!='CAMERA' or bpy.data.objects.get(camera.name)!=camera:
                fail('VERIFICATION_FAILED','dicing camera requires a local native camera identity')
        result['dicingCamera']=camera.name if camera else None
    elif kind=='BLENDER_EEVEE':
        result['eevee']=settings(scene.eevee,'SceneEEVEE',EEVEE_PRESENTATION)
        result['rayTracing']=settings(scene.eevee.ray_tracing_options,'RaytraceEEVEE')
    if kind=='BLENDER_WORKBENCH':
        result['workbenchDisplay']=settings(scene.display,'SceneDisplay',{'viewport_aa'})
        result['workbenchShading']=settings(scene.display.shading,'View3DShading')
    return result


def verify(actual,expected):
    # The authored current frame is integral. A saved subframe is an input,
    # not floating-point reconstruction error or an evaluated physics cache.
    if not matching(actual.get('time'),expected.get('time'),exact=True) or not matching(actual,expected):
        fail('VERIFICATION_FAILED','render context differs from trusted authored-source reconstruction',
             recovery='Preserve the packet. Rerun trusted authored intent into a NEW output for deliberate renderer changes; do not replace its submitted readback witnesses.')
