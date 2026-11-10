"""First-consumer trusted PointCache construction/bake lifecycle.

Internal installed-code API, not a public route. construct is supplied by the
installed adaptor, NEVER authored input/reflection. Saved JSON cannot construct
this process-local capability. Host source/payload admission must precede any
submitted native open; this module never opens a submitted file itself.
"""
from dataclasses import dataclass
from pathlib import Path
import copy
import bpy
from schemaxis.errors import fail
from . import cache_policy as policy
from . import cache_fidelity_native as fidelity


@dataclass
class Construction:
    scene: object
    plan: dict
    cache: object
    root: Path
    input_fingerprint: str
    baked: bool = False
    project_path: object = None


def resolve(scene, plan):
    if scene.name != plan['scene']:fail('VERIFICATION_FAILED','cache owning scene differs')
    if plan['kind']=='rigidBody':
        if scene.rigidbody_world is None:fail('INVALID_CACHE','rigid-body world is absent')
        return scene.rigidbody_world.point_cache
    obj=scene.objects.get(plan['object'])
    mods=[m for m in obj.modifiers if m.type=='CLOTH'] if obj else []
    if len(mods)!=1:fail('INVALID_CACHE','cloth cache requires exactly one typed modifier')
    return mods[0].point_cache


def construct(compiled, constructor, root):
    """Call a trusted finite scene constructor and capture original physics inputs."""
    plan=policy.validate(compiled)
    if list(bpy.app.version)!=[5,2,3] or bpy.app.build_hash.decode()!='e13b728c6880':
        fail('UNSUPPORTED_CACHE_RUNTIME','cache requires qualified Blender5.2.3/e13b728c6880')
    root=Path(root).absolute()
    if root.exists() or root.is_symlink():fail('OUTPUT_EXISTS','cache needs a fresh owned output directory',str(root))
    root.mkdir(parents=True)
    scene=constructor(copy.deepcopy(plan['constructor']['intent']),copy.deepcopy(plan['constructor']['dependencies']))
    if not isinstance(scene,bpy.types.Scene):fail('INVALID_CACHE','trusted constructor must return its new scene')
    cache=resolve(scene,plan)
    if cache.is_baked or cache.use_external:fail('INVALID_CACHE','constructor must supply fresh unbaked internal physics')
    scene.frame_start=plan['frameStart'];scene.frame_end=plan['frameEnd'];scene.frame_set(plan['frameStart'])
    return Construction(scene,copy.deepcopy(plan),cache,root,fidelity.inputs(scene))


def from_fresh_scene(compiled, scene, project_path):
    """Nominate actual fresh handles during installed production construction.

    Does not construct or open any document. Construct ALL consumer tokens before
    the first bake. Never call this on submitted native state: host source/cache
    admission must precede submitted opens, and verification uses fresh references.
    """
    import re
    plan=policy.validate(compiled);project=Path(project_path).absolute()
    if not re.fullmatch(r'[0-9]{4}\.blend',project.name):fail('INVALID_CACHE','public cache project requires its finite visit basename')
    if project.parent.is_symlink() or not project.parent.is_dir() or project.is_symlink():fail('INVALID_CACHE','cache publication requires an owned plain directory')
    if list(bpy.app.version)!=[5,2,3] or bpy.app.build_hash.decode()!='e13b728c6880':fail('UNSUPPORTED_CACHE_RUNTIME','cache requires qualified fixed Blender runtime')
    cache=resolve(scene,plan)
    if cache.is_baked or cache.use_external:fail('INVALID_CACHE','cache token requires fresh unbaked internal consumer')
    previous=scene.frame_current
    try:
        scene.frame_set(plan['frameStart']);fingerprint=fidelity.inputs(scene)
    finally:scene.frame_set(previous)
    return Construction(scene,copy.deepcopy(plan),cache,project.parent,fingerprint,project_path=project)


def consumer_names(scene, compiled):
    if compiled['kind']=='cloth':return [compiled['object']]
    return sorted(o.name for o in scene.rigidbody_world.collection.objects)


def prepare_consumers(compiled, scene, project_path):
    """Stage same-project capabilities and aggregate observations before baking."""
    if len(compiled)>32:fail('RESOURCE_BUDGET_EXCEEDED','cache consumer count exceeds32')
    total=0;consumers=set();tokens=[]
    for plan in compiled:
        key=(plan['kind'],plan['object'])
        if key in consumers:fail('INVALID_CACHE','cache consumers alias one actual native owner')
        consumers.add(key)
        names=consumer_names(scene,plan)
        vertices=sum(len(scene.objects[n].data.vertices) for n in names)
        loops=sum(len(scene.objects[n].data.loops) for n in names)
        total+=(vertices*24+loops*8+len(names)*128)*(plan['frameEnd']-plan['frameStart']+1)
        if total>64*1024**2:fail('RESOURCE_BUDGET_EXCEEDED','aggregate cache observations exceed64 MiB')
        tokens.append(from_fresh_scene(plan,scene,project_path))
    return tokens


def _save(path):
    preferences=bpy.context.preferences.filepaths;old=preferences.save_version
    try:
        preferences.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=str(path),check_existing=False,relative_remap=False)
    finally:preferences.save_version=old


def _check(token):
    if not isinstance(token,Construction):fail('VERIFICATION_CONTEXT_REQUIRED','cache needs fresh process-local construction')
    policy.validate(token.plan)
    if token.cache != resolve(token.scene,token.plan):fail('VERIFICATION_FAILED','cache consumer handle changed')


def bake(token, *, event=None):
    _check(token)
    if token.baked:fail('INVALID_CACHE','construction already baked; parameter changes require fresh construction')
    token.scene.frame_set(token.plan['frameStart'])
    if fidelity.inputs(token.scene)!=token.input_fingerprint:fail('INPUT_CHANGED','physics inputs changed before bake')
    cache=token.cache;plan=token.plan
    project=Path(token.project_path) if token.project_path is not None else token.root/'model.blend'
    folder=project.parent/('blendcache_'+project.stem)
    # Native disk-cache toggling needs an already saved owning .blend path.
    # Setting the flag on an unsaved scene can leave an unusable disk bake.
    _save(project)
    cache.frame_start=plan['frameStart'];cache.frame_end=plan['frameEnd'];cache.frame_step=1
    cache.name=plan['id'];cache.use_external=False;cache.use_library_path=False
    disk=plan['storage']=='disk'
    if cache.use_disk_cache != disk:
        # Establish the solver's native point-cache backing before conversion.
        token.scene.frame_set(min(plan['frameEnd'],plan['frameStart']+1))
        token.scene.frame_set(plan['frameStart'])
        cache.use_disk_cache=disk
    cache.filepath='//'+folder.name+'/' if plan['storage']=='disk' else ''
    if cache.use_disk_cache != (plan['storage']=='disk'):fail('VERIFICATION_FAILED','native refused requested cache storage')
    _save(project)
    with bpy.context.temp_override(scene=token.scene,point_cache=cache):
        if event is not None:event('bake-start',plan['id'])
        result=bpy.ops.ptcache.bake(bake=True)
        if event is not None:event('bake-complete',plan['id'])
    if result!={'FINISHED'} or not cache.is_baked:fail('VERIFICATION_FAILED','native cache bake did not finish')
    token.baked=True
    _save(project)
    if not folder.exists():folder.mkdir()
    all_files=policy.inventory(folder)
    files={name:value for name,value in all_files.items() if name.rsplit('_',2)[0]==plan['id']}
    if plan['storage']=='disk' and not files:fail('VERIFICATION_FAILED','disk bake produced no owned cache files')
    if plan['storage']=='packed' and files:fail('VERIFICATION_FAILED','packed bake produced external files')
    geometry=fidelity.observe(token.scene,consumer_names(token.scene,plan),list(range(plan['frameStart'],plan['frameEnd']+1)))
    return {'version':policy.VERSION,'plan':plan,'inputFingerprint':token.input_fingerprint,'geometry':geometry,
            'isBaked':True,'files':files,'nativeType':plan['nativeType']}


def verify_inputs(scene, compiled, fresh_input_fingerprint, *, project_path=None):
    """Fresh fingerprint is supplied by trusted reconstruction, not saved metadata."""
    policy.validate(compiled);cache=resolve(scene,compiled)
    project=Path(project_path or bpy.data.filepath)
    folder='blendcache_'+project.stem
    if (not cache.is_baked or cache.use_external or cache.frame_start!=compiled['frameStart']
            or cache.frame_end!=compiled['frameEnd'] or cache.frame_step!=1
            or cache.name!=compiled['id'] or cache.use_disk_cache!=(compiled['storage']=='disk')
            or cache.use_library_path or cache.filepath!=('//'+folder+'/' if compiled['storage']=='disk' else '')):
        fail('VERIFICATION_FAILED','saved cache owner/range/storage/bake state differs')
    previous=scene.frame_current
    try:
        scene.frame_set(compiled['frameStart'])
        if fidelity.inputs(scene)!=fresh_input_fingerprint:fail('INPUT_CHANGED','saved cache physics inputs differ from fresh constructor')
    finally:scene.frame_set(previous)
