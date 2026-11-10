"""Semantic admission for reusable layered surfaces and image-sampler roles."""
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from schemaxis.pipeline import name
from .surface_materials_schema import fields


def walk(value,location):
    if isinstance(value,dict):
        yield value,location
        for key,item in value.items():yield from walk(item,location+'.'+key)
    elif isinstance(value,list):
        for i,item in enumerate(value):yield from walk(item,f'{location}[{i}]')


def validate(values,images,existing,where='production.surfaceMaterials'):
    if not isinstance(values,list) or len(values)>128:
        fail('INVALID_SURFACE_MATERIAL','provide at most 128 named layered surfaces',where)
    image_ids={image['id']:image for image in images};used=set(existing);result=[]
    for i,item in enumerate(values):
        loc=f'{where}[{i}]';surface=validate_arguments(fields(),item,location=loc)
        name(surface['id'],loc+'.id')
        if surface['id'] in used:fail('DUPLICATE_ID','surface and graph/DAG materials share one material namespace',loc+'.id')
        used.add(surface['id']);samplers={};roles={}
        scatter=surface['subsurface']['kind']
        if scatter=='thin' and surface['wall']!='thin':
            fail('INVALID_SURFACE_MATERIAL','thin scattering requires a thin wall',loc+'.subsurface')
        if surface['wall']=='thin' and scatter not in ('off','thin'):
            fail('INEFFECTIVE_SURFACE_SOURCE','thin walls do not use subsurface radius, distance or method; choose the thin scattering layer',loc+'.subsurface')
        if surface['wall']=='thin' and surface['realtime']['thickness']['kind']!='automatic':
            fail('INEFFECTIVE_SURFACE_SOURCE','a thin wall always uses zero slab thickness; explicit bulk thickness belongs to a solid wall',loc+'.realtime.thickness')
        if surface['wall']=='thin' and surface['realtime']['shadowThickness']:
            fail('INEFFECTIVE_SURFACE_SOURCE','a thin wall has no bulk thickness to estimate from shadows',loc+'.realtime.shadowThickness')
        for j,sampler in enumerate(surface['samplers']):
            here=f'{loc}.samplers[{j}]'
            if sampler['id'] in samplers:fail('DUPLICATE_ID','sampler roles must be distinct within this surface',here+'.id')
            if sampler['image'] not in image_ids:fail('UNKNOWN_REFERENCE','sampler must reference a captured production image',here+'.image')
            if sampler['coordinates']['kind']=='uv' and sampler['projection']['kind']!='flat':
                fail('INVALID_SURFACE_SAMPLER','UV coordinates require flat image projection; use generated/object coordinates for spatial projections',here+'.projection')
            samplers[sampler['id']]=sampler;roles[sampler['id']]=set()
        for source,here in walk(surface,loc):
            if 'sampler' not in source:continue
            sampler=samplers.get(source['sampler'])
            if sampler is None:fail('UNKNOWN_REFERENCE','source must reference a local named sampler',here+'.sampler')
            image=image_ids[sampler['image']]
            if 'channel' in source:
                channel=source['channel'];roles[sampler['id']].add('scalar:'+channel)
                if channel in ('red','green','blue') and image['colourSpace']!='Non-Color':
                    fail('INVALID_SURFACE_IMAGE','scalar RGB channels require a Non-Color image; alpha or explicit linear luminance can reuse a colour image',here)
                if channel=='alpha' and image['alphaMode']=='ignore':
                    fail('INEFFECTIVE_SURFACE_SOURCE','this image explicitly ignores alpha; choose a meaningful alpha interpretation',here)
            elif 'tint' in source:roles[sampler['id']].add('colour')
            else:
                roles[sampler['id']].add('normal')
                if image['colourSpace']!='Non-Color':fail('INVALID_SURFACE_IMAGE','normal-map RGB encodes vectors and requires a Non-Color image',here)
                if source['space']['kind']=='tangent':
                    uv=source['space']['uv']
                    if sampler['projection']['kind']!='flat':
                        fail('INVALID_SURFACE_NORMAL','a tangent normal map needs a flat UV sampling route; use a named mesh UV projection or explicit object/world vector encoding',here+'.space')
                    if uv['kind']=='sampler' and sampler['coordinates']['kind']!='uv':
                        fail('INVALID_SURFACE_NORMAL','sampler tangent basis needs a UV sampler; choose an explicit stored UV basis or object/world normals',here+'.space.uv')
        # Native layer defaults intentionally remain explicit in the artist
        # contract, while expert graph additions are absent unless authored.
        surface['samplers']=list(samplers.values());result.append(surface)
    return result


def is_zero(source):
    return (source['kind']=='constant' and source['value']==0 or
            source['kind']=='sample' and source['range']==[0,0])


def applicability(surfaces,renderer,where='production.surfaceMaterials'):
    """Reject effects absent from EEVEE; Workbench is an explicit preview."""
    if renderer['kind']!='eevee':return
    for i,surface in enumerate(surfaces):
        loc=f'{where}[{i}]';specular=surface['specular']
        inactive=[]
        if not is_zero(surface['diffuse']['roughness']):inactive.append('diffuse.roughness')
        if not is_zero(specular['anisotropy']):inactive.append('specular.anisotropy')
        scatter=surface['subsurface']
        if scatter['kind'] not in ('off','diffusion','thin') and not is_zero(scatter['weight']):inactive.append('subsurface')
        if scatter['kind']=='thin' and not is_zero(scatter['weight']) and not is_zero(scatter['anisotropy']):inactive.append('subsurface.anisotropy')
        if not is_zero(surface['thinFilm']['thicknessNanometres']):inactive.append('thinFilm')
        if surface['displacement']['kind'] in ('geometry','both'):inactive.append('displacement')
        if surface['realtime']['transmission']=='screen' and renderer['rayTracing']['kind']!='screen':
            fail('INEFFECTIVE_SURFACE_SOURCE','screen transmission requires EEVEE screen ray tracing in the render settings',loc+'.realtime.transmission')
        if inactive:fail('UNSUPPORTED_SURFACE_RENDERER','these physical surface effects require Cycles',loc,fields=inactive)


def graph_applicability(spec,renderer):
    """Known fixed-engine omissions apply to both artist and expert routes."""
    engine=renderer['kind']
    if engine not in ('cycles','eevee'):return
    from .surface_compile import all_material_graphs
    graphs=all_material_graphs(spec)+[g for g in spec.get('nodeGroups',[]) if g['family']=='material']
    for graph in graphs:
        linked={(l['to']['node'],l['to']['socket']) for l in graph['links']}
        for node in graph['nodes']:
            values=node['values'];props=node['properties'];kind=node['kind'];inactive=[]
            if kind=='image' and props['interpolation']=='Smart' and engine=='cycles' and renderer.get('shadingSystem')!='osl':
                fail('UNSUPPORTED_SHADER_BACKEND','Smart image filtering requires Cycles with the built-in OSL shading system',
                     'production.materials.'+graph['id']+'.'+node['id']+'.interpolation')
            if engine!='eevee':continue
            def active(key):return (node['id'],key) in linked or values.get(key,0)!=0
            if kind=='principled':
                for key in ('diffuseRoughness','anisotropy','thinFilmThickness'):
                    if active(key):inactive.append(key)
                if active('subsurface'):
                    if props.get('subsurfaceMethod','RANDOM_WALK')!='BURLEY' and not values.get('thinWall'):inactive.append('subsurfaceMethod')
                    for key in ('subsurfaceAnisotropy','subsurfaceIor'):
                        if key in values or (node['id'],key) in linked:
                            if key=='subsurfaceIor' or active(key):inactive.append(key)
            elif kind=='image':
                if props['interpolation']=='Smart':inactive.append('interpolation')
                if props.get('projection')=='BOX' and props['extension'] in ('CLIP','EXTEND'):inactive.append('extension')
            elif kind=='displacement' and graph.get('surfacePolicy',{}).get('displacement') in ('DISPLACEMENT','BOTH'):inactive.append('displacement')
            if inactive:fail('UNSUPPORTED_SURFACE_RENDERER','the selected EEVEE engine does not implement these authored surface effects',
                             'production.materials.'+graph['id']+'.'+node['id'],fields=inactive)
