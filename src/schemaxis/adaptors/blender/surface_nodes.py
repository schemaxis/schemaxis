"""Reviewed layered surface sockets; optional additions preserve old contracts."""
from .node_specs import node,socket,number,vector,colour,choice,boolean,text,S,V,C
from schemaxis.errors import fail


def optional(specification):
    """New expert controls do not inject fields into existing normalized graphs."""
    return {k:v for k,v in specification.items() if k!='default'}


def scalar(native,minimum=0,maximum=1):
    return socket(native,'number',optional(number(minimum=minimum,maximum=maximum)))


def vector_input(native,minimum=None,maximum=None):
    spec=optional(vector())
    if minimum is not None:spec['items']['minimum']=minimum
    if maximum is not None:spec['items']['maximum']=maximum
    return socket(native,'vector',spec)


def colour_input(native):
    return socket(native,'colour',optional(colour()))


PRINCIPLED_INPUTS={
    'thinWall':socket('Thin Wall','boolean',optional(boolean())),
    'diffuseRoughness':scalar('Diffuse Roughness'),
    'subsurface':scalar('Subsurface Weight'),
    'subsurfaceRadius':vector_input('Subsurface Radius',0,1e6),
    'subsurfaceScale':scalar('Subsurface Scale',0,1e6),
    'subsurfaceIor':scalar('Subsurface IOR',1,4),
    'subsurfaceAnisotropy':scalar('Subsurface Anisotropy',-1,1),
    'specularLevel':scalar('Specular IOR Level'),
    'specularTint':colour_input('Specular Tint'),
    'anisotropy':scalar('Anisotropic',-1,1),
    'anisotropyRotation':scalar('Anisotropic Rotation',-1,1),
    'tangent':vector_input('Tangent'),
    'coatRoughness':scalar('Coat Roughness'),
    'coatIor':scalar('Coat IOR',1,4),
    'coatTint':colour_input('Coat Tint'),
    'coatNormal':vector_input('Coat Normal'),
    'sheen':scalar('Sheen Weight'),
    'sheenRoughness':scalar('Sheen Roughness'),
    'sheenTint':colour_input('Sheen Tint'),
    'thinFilmThickness':scalar('Thin Film Thickness',0,1e6),
    'thinFilmIor':scalar('Thin Film IOR',1,4),
}


def extend(materials):
    materials['principled']['inputs'].update(PRINCIPLED_INPUTS)
    materials['principled']['properties'].update({
        'distribution':('distribution',optional(choice('MULTI_GGX',['GGX','MULTI_GGX']))),
        'subsurfaceMethod':('subsurface_method',optional(choice('RANDOM_WALK',['BURLEY','RANDOM_WALK','RANDOM_WALK_SKIN']))),
    })
    materials['normalMap']['properties'].update({
        'space':('space',optional(choice('TANGENT',['TANGENT','OBJECT','WORLD']))),
        'uvMap':('uv_map',optional(text())),
        'convention':('convention',optional(choice('OPENGL',['OPENGL','DIRECTX']))),
        'base':('base',optional(choice('DISPLACED',['ORIGINAL','DISPLACED']))),
    })
    materials['bump']['inputs']['filterWidth']=scalar('Filter Width',0,1e6)
    materials['mixColour']['properties']['clamp']=('use_clamp',optional(boolean()))
    # EEVEE distinguishes a connected thickness from its automatic fallback;
    # an unlinked literal socket value does not override object thickness.
    materials['output']['inputs']['thickness']=socket('Thickness','number')
    materials['image']['properties'].update({
        'projection':('projection',optional(choice('FLAT',['FLAT','BOX','SPHERE','TUBE']))),
        'projectionBlend':('projection_blend',optional(number(minimum=0,maximum=1))),
    })
    materials.update({
        'separateColour':node('ShaderNodeSeparateColor',{'colour':C('Color')},
                              {'red':S('Red'),'green':S('Green'),'blue':S('Blue')}),
        'tangent':node('ShaderNodeTangent',outputs={'tangent':V('Tangent')},properties={
            'direction':('direction_type',choice('UV_MAP',['UV_MAP','RADIAL'])),
            'axis':('axis',optional(choice('Z',['X','Y','Z']))),
            'uvMap':('uv_map',optional(text())),
        }),
        'vectorTransform':node('ShaderNodeVectorTransform',{'vector':V('Vector')},{'vector':V('Vector')},{
            'type':('vector_type',choice('VECTOR',['VECTOR','POINT','NORMAL'])),
            'from':('convert_from',choice('OBJECT',['OBJECT','WORLD','CAMERA'])),
            'to':('convert_to',choice('WORLD',['OBJECT','WORLD','CAMERA'])),
        }),
        'displacement':node('ShaderNodeDisplacement',{
            'height':S('Height'),'midlevel':S('Midlevel',.5),'scale':S('Scale',.01),'normal':V('Normal'),
        },{'displacement':V('Displacement')},{'space':('space',choice('OBJECT',['OBJECT','WORLD']))}),
    })


def validate_node(kind,values,properties,where):
    """New expert controls may not silently select inactive native settings."""
    if kind=='principled':
        if 'subsurfaceIor' in values and properties.get('subsurfaceMethod')!='RANDOM_WALK_SKIN':
            fail('INACTIVE_SURFACE_INPUT','subsurface IOR applies only to the skin random-walk method',where+'.values.subsurfaceIor')
        if values.get('thinWall') and any(k in values for k in ('subsurfaceRadius','subsurfaceScale')):
            fail('INACTIVE_SURFACE_INPUT','thin walls ignore subsurface radius and scale',where+'.values')
    if kind=='image' and 'projectionBlend' in properties and properties.get('projection','FLAT')!='BOX':
        fail('INACTIVE_SURFACE_INPUT','projection blend applies only to box projection',where+'.properties.projectionBlend')
    if kind=='normalMap' and properties.get('space','TANGENT')!='TANGENT' and properties.get('uvMap'):
        fail('INACTIVE_SURFACE_INPUT','a named tangent basis applies only to tangent-space normals',where+'.properties.uvMap')
    if kind=='tangent' and properties.get('direction')=='UV_MAP' and 'axis' in properties:
        fail('INACTIVE_SURFACE_INPUT','the radial axis does not control UV tangents',where+'.properties.axis')
    if kind=='tangent' and properties.get('direction','RADIAL')!='UV_MAP' and properties.get('uvMap'):
        fail('INACTIVE_SURFACE_INPUT','a named UV set does not control radial tangents',where+'.properties.uvMap')
