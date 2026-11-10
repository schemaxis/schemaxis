"""Compile closed artist intent through the reviewed material graph contract."""
from .surface_graph import Graph
from .node_catalogue import validate_graph


def compile_surface(surface,images=()):
    graph=Graph(surface,images)
    scatter=surface['subsurface'];specular=surface['specular'];coat=surface['coat']
    shader=graph.node('principled',properties={
        'distribution':{'multipleScatter':'MULTI_GGX','singleScatter':'GGX'}[specular['energy']],
        'subsurfaceMethod':{'off':'RANDOM_WALK','thin':'RANDOM_WALK','diffusion':'BURLEY',
                            'randomWalk':'RANDOM_WALK','skin':'RANDOM_WALK_SKIN'}[scatter['kind']],
    })
    scalars={
        'metallic':surface['metallic'],'roughness':surface['roughness'],'ior':surface['ior'],
        'alpha':surface['coverage'],'transmission':surface['transmission'],
        'diffuseRoughness':surface['diffuse']['roughness'],
        'specularLevel':specular['level'],'anisotropy':specular['anisotropy'],
        'coat':coat['weight'],'coatRoughness':coat['roughness'],'coatIor':coat['ior'],
        'sheen':surface['sheen']['weight'],'sheenRoughness':surface['sheen']['roughness'],
        'emissionStrength':surface['emission']['strength'],
        'thinFilmThickness':surface['thinFilm']['thicknessNanometres'],'thinFilmIor':surface['thinFilm']['ior'],
    }
    for key,source in scalars.items():graph.bind(shader,key,graph.scalar(source))
    for key,source in [('colour',surface['baseColour']),('specularTint',specular['tint']),
                       ('coatTint',coat['tint']),('sheenTint',surface['sheen']['tint']),
                       ('emission',surface['emission']['colour'])]:
        graph.bind(shader,key,graph.colour(source,clamp=key!='emission'))
    graph.bind(shader,'anisotropyRotation',graph.scale(graph.scalar(specular['rotationDegrees']),1/360))
    shader['values']['thinWall']=surface['wall']=='thin'
    shader['values']['subsurface']=0
    if scatter['kind']!='off':
        graph.bind(shader,'subsurface',graph.scalar(scatter['weight']))
        if scatter['kind']!='thin':
            shader['values'].update(subsurfaceRadius=scatter['relativeRadius'],subsurfaceScale=scatter['distance'])
        if 'anisotropy' in scatter:graph.bind(shader,'subsurfaceAnisotropy',graph.scalar(scatter['anisotropy']))
        if 'ior' in scatter:graph.bind(shader,'subsurfaceIor',graph.scalar(scatter['ior']))
    tangent=specular['tangent']
    if tangent['kind']!='automatic':
        properties={'direction':'UV_MAP','uvMap':tangent['set'].get('name','')} if tangent['kind']=='uv' else {'direction':'RADIAL','axis':tangent['axis'].upper()}
        node=graph.node('tangent',properties=properties);graph.bind(shader,'tangent',graph.output(node,'tangent'))
    normal=graph.normal(surface['normal'])
    if normal is not None:graph.bind(shader,'normal',normal)
    coat_normal=coat['normal']
    if coat_normal['kind']=='followBase':coat_port=normal
    elif coat_normal['kind']=='detail':coat_port=graph.normal(coat_normal['normal'])
    else:coat_port=None
    if coat_port is not None:graph.bind(shader,'coatNormal',coat_port)
    output=graph.node('output')
    realtime=surface['realtime'];thickness=realtime['thickness']
    distance=0 if surface['wall']=='thin' else graph.scalar(thickness['distance']) if thickness['kind']!='automatic' else None
    if distance is not None:
        from .surface_graph import Port
        if not isinstance(distance,Port):distance=graph.output(graph.node('value',properties={'value':distance}),'value')
        graph.bind(output,'thickness',distance)
    graph.bind(output,'surface',graph.output(shader,'shader'))
    displacement=surface['displacement']
    if displacement['kind']!='none':
        node=graph.node('displacement',{'midlevel':displacement['midlevel'],'scale':displacement['distance']},
                        {'space':displacement['space'].upper()})
        graph.bind(node,'height',graph.scalar(displacement['height']))
        graph.bind(output,'displacement',graph.output(node,'displacement'))
    result=validate_graph({'id':surface['id'],'nodes':graph.nodes,'links':graph.links,
                           **{k:surface[k] for k in ('viewportColour','displayTexture')}},
                          'material','production.surfaceMaterials.'+surface['id'],material_display=True)
    # Internal compiled metadata is never accepted by the authored graph schema.
    result['surfacePolicy']={
        'displacement':{'none':'BUMP','bump':'BUMP','geometry':'DISPLACEMENT','both':'BOTH'}[displacement['kind']],
        'thickness':'SLAB' if surface['wall']=='thin' or thickness['kind']=='slab' else 'SPHERE',
        'raytracedTransmission':realtime['transmission']=='screen',
        'shadowThickness':realtime['shadowThickness'],
    }
    return result


def all_material_graphs(spec):
    """Keep normalized artist intent stable across repeated public planning."""
    return spec.get('materialGraphs',[])+[compile_surface(s,spec.get('images',[])) for s in spec.get('surfaceMaterials',[])]
