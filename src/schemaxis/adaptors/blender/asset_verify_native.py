"""Reconstruct imported asset state from the declared captured inputs.

Saved readbacks are comparison results, never authoritative source witnesses.
Only JSON-compatible signatures survive opening the submitted native project.
"""
import copy
import bpy
from schemaxis.errors import fail
from schemaxis.pipeline import RuntimeClosure
from .asset_fidelity import matching


def references(master,selection,prepared,visit,sources):
    spec=master.document['scenes'][0].get('production')
    if not spec or not spec['assets']:return None
    from .native import Backend,configure_render
    from .production_native import Production
    from .production_asset_snapshot import snapshot_asset_members
    # Match construction's empty factory scene and deterministic resource names.
    # Reference geometry/data inspection needs no Cycles accelerator. The actual
    # submitted scene still undergoes its own declared device/render checks.
    bpy.ops.wm.read_factory_settings(use_empty=True);scene=bpy.context.scene
    configure_render(scene,{**prepared['renderSettings'],'device':'CPU'})
    camera=bpy.data.objects.new('__schemaxis_camera',bpy.data.cameras.new('__schemaxis_camera'))
    scene.collection.objects.link(camera);scene.camera=camera
    active=RuntimeClosure(master,Backend(sources));active.activate(selection.roots);active.apply(visit)
    production=Production(copy.deepcopy(spec),active.handles,sources)
    # Reproduce authored edits, fields, bindings and animation before observing
    # the source-owned data; no untrusted submitted .blend has been opened yet.
    return {a['id']:snapshot_asset_members(production.objects[a['id']]) for a in spec['assets']}


def verify(actual,expected):
    if expected is None:return
    found={a['id']:a['fidelity'] for a in actual['assets']}
    if not matching(found,expected):
        fail('VERIFICATION_FAILED','native assets differ from trusted captured-source reconstruction')
