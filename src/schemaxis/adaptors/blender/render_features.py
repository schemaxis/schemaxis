"""Public composition of the started layer, NPR and simulation-cache features.

Each field keeps a typed family compiler. This module binds their common logical
resource namespace and aggregate publication/engine policy; it exposes no RNA.
Absent fields leave the historical normalized production shape unchanged.
"""
from . import render_bundles, render_aovs, world_resources
from .surface_compile import all_material_graphs


FIELDS = (*render_bundles.OPTIONS, *render_aovs.OPTIONS, *world_resources.OPTIONS,
          'npr', 'simulationCaches')


def schema_properties():
    from . import npr, cache_policy
    return {**render_bundles.schema_properties(), **render_aovs.schema_properties(),
            **world_resources.schema_properties(), 'npr': npr.schema_property(public=True),
            'simulationCaches': cache_policy.schema_property()}


def normalize(value, result, graph_nodes):
    if not any(key in value for key in FIELDS):return
    kinds = {identity: spec['filter'] for identity, spec in graph_nodes.items()}
    kinds.update({obj['id']: obj['kind'] for obj in result['objects']})
    kinds.update({asset['id']: 'asset' for asset in result['assets']})
    kinds.update({rig['id']: 'rig' for rig in result['rigs']})
    materials = {identity for identity, spec in graph_nodes.items() if spec['filter'] == 'material'}
    graphs = all_material_graphs(result);materials.update(graph['id'] for graph in graphs)
    collections = {item['id'] for item in result['collections']}
    assets = {item['id'] for item in result['assets']}
    images = {item['id'] for item in result['images']}
    if any(key in value for key in (*render_bundles.OPTIONS, *render_aovs.OPTIONS, *world_resources.OPTIONS, 'npr')):
        worlds = world_resources.validate(value.get('worlds', []), images=images,
                                           scene_world=value.get('sceneWorld', ''))
        result.update(worlds=worlds, sceneWorld=value.get('sceneWorld', ''))
        result.update(render_bundles.validate({**result, **{key: value[key] for key in render_bundles.OPTIONS if key in value}},
            kinds=kinds, materials=materials, collections=collections, assets=assets,
            worlds={world['id'] for world in worlds}))
        result['materialAovs'] = render_aovs.validate(value.get('materialAovs', []),
            aovs=result['renderAovs'], materials=materials, graphs=graphs,
            surfaces={surface['id'] for surface in result.get('surfaceMaterials', [])},
            groups=result['nodeGroups'], assets=assets, worlds={world['id'] for world in worlds})
        if 'npr' in value:
            from .npr import validate_public
            result['npr'] = validate_public(value['npr'], renderer='cycles', layers={layer['id'] for layer in result['viewLayers']},
                objects=set(kinds)-materials, collections=collections, materials=materials, kinds=kinds)
    if 'simulationCaches' in value:
        from .cache_policy import validate_public
        result['simulationCaches'] = validate_public(value['simulationCaches'], kinds=kinds,
            rigid_bodies=result['rigidBodies'], cloth=result['cloth'],
            frame_start=result['frameStart'], frame_end=result['frameEnd'])


def applicability(spec, render, size):
    if not any(key in spec for key in FIELDS):return
    engine = render['renderer']['kind']
    if 'viewLayers' in spec:render_bundles.validate_engine(spec, engine)
    world_resources.validate_engine(spec.get('worlds', []), engine)
    if 'viewLayers' in spec:
        from .render_bundle_data import validate_context
        validate_context(spec, render)
    if 'npr' in spec:
        from schemaxis.errors import fail
        if engine != 'cycles':
            fail('UNSUPPORTED_NPR_RENDERER', 'the qualified public Freestyle contract requires Cycles', 'render.renderer')
    return render_bundles.budget(spec, size) if 'viewLayers' in spec else None


def output_count(spec):
    return (sum(len(bundle['frames']) * len(bundle['outputs']) for bundle in spec.get('renderBundles', []))
            +sum(cache['frameEnd']-cache['frameStart']+1 for cache in spec.get('simulationCaches', []) if cache['storage']=='disk'))


def verify_cache_publications(spec, artifacts, directory, state):
    """Bind every native disk frame to its typed consumer before fresh replay.

    These declarations are an early membership gate. Fresh reconstruction still
    compares the complete managed payload directory before submitted open.
    """
    import re
    from pathlib import Path
    from schemaxis.errors import fail
    expected={(cache['id'],frame) for cache in spec.get('simulationCaches', [])
              if cache['storage']=='disk' for frame in range(cache['frameStart'],cache['frameEnd']+1)}
    actual=set();root=Path(directory).absolute();folder=root/f'blendcache_{state:04d}'
    for artifact in artifacts:
        identity=artifact.get('cacheId');path=Path(artifact.get('file',''))
        match=re.fullmatch(r'([A-Za-z][A-Za-z0-9_-]{0,62})_([0-9]{6})_([0-9]{2})\.bphys',path.name)
        if (match is None or match.group(1)!=identity or path.parent!=folder
                or artifact.get('relativePath')!=str(path.relative_to(root))):
            fail('VERIFICATION_FAILED','simulation cache publication path/consumer differs')
        key=(identity,int(match.group(2)))
        if key in actual:fail('VERIFICATION_FAILED','duplicate simulation cache frame publication')
        actual.add(key)
    if actual!=expected:fail('VERIFICATION_FAILED','simulation cache frame membership differs')


def verify_bundle_publications(spec,artifacts,directory,state,size):
    from pathlib import Path
    from schemaxis.errors import fail
    from .render_bundle_layout import jobs
    from .render_bundle_data import layout
    expected=jobs(spec,f'{state:04d}') if spec.get('renderBundles') else []
    if len(artifacts)!=len(expected):fail('VERIFICATION_FAILED','render bundle publication membership differs')
    root=Path(directory).absolute()/'renders'/'bundles'
    for artifact,job in zip(artifacts,expected):
        if (any(artifact.get(key)!=job[key] or type(artifact.get(key))!=type(job[key])
                for key in ('bundle','output','frame','format'))
                or artifact.get('file')!=str(root/job['file'])):
            fail('VERIFICATION_FAILED','render bundle job/path differs from typed declaration')
        layout(job,root/job['file'],size)
