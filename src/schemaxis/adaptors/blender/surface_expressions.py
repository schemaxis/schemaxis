"""Finite artist colour/scalar sources and reusable texture sampling intent."""
from .mesh_data import NAME,array
from .node_specs import number,choice,vector
from .render_policy import rgb,record,options,variant,union


def scalar(default=0,minimum=0,maximum=1,sample_range=None):
    if sample_range is None:sample_range=[minimum,min(maximum,max(minimum+1,1))]
    return union([
        variant('constant',{'value':number(default,minimum=minimum,maximum=maximum)}),
        variant('sample',{'sampler':{**NAME,'required':True},
                         'channel':choice('red',['red','green','blue','alpha','luminance']),
                         'range':{'type':'array','items':{'type':'number','minimum':minimum,'maximum':maximum},
                                  'minItems':2,'maxItems':2,'default':sample_range}}),
    ],{'kind':'constant','value':default})


def colour_source(default=(.8,.8,.8)):
    return union([
        variant('constant',{'value':rgb(default)}),
        variant('sample',{'sampler':{**NAME,'required':True},'tint':rgb((1,1,1))}),
    ],{'kind':'constant','value':list(default)})


UV_SET=union([variant('active',{}),variant('named',{'name':{**NAME,'required':True}})],{'kind':'active'})
UV_TRANSFORM=options({
    'offset':{'type':'array','items':{'type':'number','minimum':-1e6,'maximum':1e6},'minItems':2,'maxItems':2,'default':[0,0]},
    'tile':{'type':'array','items':{'type':'number','minimum':-1e6,'maximum':1e6},'minItems':2,'maxItems':2,'default':[1,1]},
    'rotationDegrees':number(0,minimum=-360,maximum=360),
})
SPATIAL_TRANSFORM=options({'translation':vector(),'rotationDegrees':vector(),'scale':vector((1,1,1))})
COORDINATES=union([
    variant('uv',{'set':UV_SET,'transform':UV_TRANSFORM}),
    variant('generated',{'transform':SPATIAL_TRANSFORM}),
    variant('object',{'transform':SPATIAL_TRANSFORM}),
],{'kind':'uv'})
SAMPLER=record({
    'id':{**NAME,'required':True},'image':{**NAME,'required':True},
    'coordinates':COORDINATES,
    'projection':union([variant('flat',{}),variant('box',{'blend':number(0,minimum=0,maximum=1)}),
                        variant('sphere',{}),variant('tube',{})],{'kind':'flat'}),
    'wrap':choice('repeat',['repeat','extend','clip','mirror']),
    'filter':choice('linear',['linear','nearest','cubic','smart']),
})


def sampler_list():
    # A material's sampler IDs are local. Resources reuse production.images.
    return {**array(SAMPLER,32),'default':[]}
