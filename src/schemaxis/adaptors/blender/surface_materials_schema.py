"""Layered surface artist intent, independent of native node/property names."""
from .mesh_data import NAME,array
from .node_specs import number,boolean,choice
from .node_catalogue import material_display_fields
from .render_policy import record,options,variant,union
from .surface_expressions import scalar,colour_source,UV_SET,sampler_list


NORMAL_UV=union([variant('sampler',{}),variant('active',{}),
                 variant('named',{'name':{**NAME,'required':True}})],{'kind':'sampler'})
MAP=record({
    'sampler':{**NAME,'required':True},'strength':scalar(1,0,5),
    'space':union([
        variant('tangent',{'uv':NORMAL_UV}),
        variant('object',{}),variant('world',{}),
    ],{'kind':'tangent'}),
    'convention':choice('openGL',['openGL','directX']),
    'base':choice('displaced',['original','displaced']),
})
BUMP=options({'height':scalar(.5),'strength':scalar(1),'distance':number(.001,minimum=0,maximum=1e6),
              'invert':boolean(),'filterWidth':number(.1,minimum=0,maximum=1e6)})


def detail():
    return union([
        variant('geometric',{}),
        variant('normalMap',{'map':required_map()}),
        variant('heightBump',{'bump':BUMP}),
        variant('normalAndBump',{'map':required_map(),'bump':BUMP}),
    ],{'kind':'geometric'})


def required_map():
    return {**MAP,'required':True}


SCATTER={
    'weight':scalar(1),
    'relativeRadius':{'type':'array','items':{'type':'number','minimum':0,'maximum':1e6},
                      'minItems':3,'maxItems':3,'default':[1,.2,.1]},
    'distance':number(.005,minimum=0,exclusiveMinimum=True,maximum=1e6),
}
SUBSURFACE=union([
    variant('off',{}),variant('diffusion',SCATTER),
    variant('randomWalk',{**SCATTER,'anisotropy':scalar(0,-1,1)}),
    variant('skin',{**SCATTER,'anisotropy':scalar(.8,-1,1),'ior':scalar(1.4,1,4)}),
    variant('thin',{'weight':scalar(1),'anisotropy':scalar(0,-1,1)}),
],{'kind':'off'})
TANGENT=union([
    variant('automatic',{}),variant('uv',{'set':UV_SET}),
    variant('radial',{'axis':choice('z',['x','y','z'])}),
],{'kind':'automatic'})
SPECULAR=options({'level':scalar(.5),'tint':colour_source((1,1,1)),
                  'anisotropy':scalar(0,-1,1),'rotationDegrees':scalar(0,-360,360,[-180,180]),
                  'tangent':TANGENT,'energy':choice('multipleScatter',['multipleScatter','singleScatter'])})
COAT_NORMAL=union([variant('followBase',{}),variant('geometric',{}),variant('detail',{'normal':detail()})],{'kind':'followBase'})
COAT=options({'weight':scalar(0),'roughness':scalar(.03),'ior':scalar(1.5,1,4),
              'tint':colour_source((1,1,1)),'normal':COAT_NORMAL})
SHEEN=options({'weight':scalar(0),'roughness':scalar(.5),'tint':colour_source((1,1,1))})
EMISSION=options({'colour':colour_source((1,1,1)),'strength':scalar(0,0,1e6)})
THIN_FILM=options({'thicknessNanometres':scalar(0,0,1e6),'ior':scalar(1.33,1,4)})
HEIGHT={'height':scalar(.5),'midlevel':number(.5,minimum=0,maximum=1),
        'distance':number(.01,minimum=0,maximum=1e6),'space':choice('object',['object','world'])}
DISPLACEMENT=union([variant('none',{}),variant('bump',HEIGHT),variant('geometry',HEIGHT),variant('both',HEIGHT)],{'kind':'none'})
REALTIME=options({'transmission':choice('probe',['probe','screen']),
    'thickness':union([variant('automatic',{}),
        variant('sphere',{'distance':scalar(.01,0,1e6)}),
        variant('slab',{'distance':scalar(.01,0,1e6)})],{'kind':'automatic'}),
    'shadowThickness':boolean()})


def fields():
    return {'id':{**NAME,'required':True},'samplers':sampler_list(),
        'baseColour':colour_source(),'metallic':scalar(0),'roughness':scalar(.5),'ior':scalar(1.5,1,4),
        'coverage':scalar(1),'wall':choice('solid',['solid','thin']),
        'diffuse':options({'roughness':scalar(0)}),'subsurface':SUBSURFACE,'specular':SPECULAR,
        'transmission':scalar(0),'coat':COAT,'sheen':SHEEN,'emission':EMISSION,'thinFilm':THIN_FILM,
        'normal':detail(),'displacement':DISPLACEMENT,'realtime':REALTIME,**material_display_fields()}


def schema_property():
    from schemaxis.schema import arguments_schema
    return array(arguments_schema(fields()),128)
