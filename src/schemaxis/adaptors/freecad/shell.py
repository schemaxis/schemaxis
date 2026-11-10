"""Uniform wall intent and exact opening-face selection for native Thickness."""
from schemaxis.errors import fail
from .faces import NORMALS,resolve

OPENING={'type':'object','properties':{
    'face':{'type':'enum','values':list(NORMALS),'required':True},
    'position':{'type':'enum','values':['outermost','innermost'],'default':'outermost'}}}


def declaration(factory,length):
    return factory('PartDesign::Thickness',{
        'thickness':{**length,'default':2},
        'openings':{'type':'array','items':OPENING,'minItems':1,'maxItems':12,'required':True},
        'side':{'type':'enum','values':['inward','outward'],'default':'inward'},
        'corners':{'type':'enum','values':['sharp','rounded'],'default':'sharp'},
        'intersectionHandling':{'type':'boolean','default':False}},('base',))


def validate(options,identity):
    keys=[(f['face'],f['position']) for f in options['openings']]
    if len(set(keys))!=len(keys):fail('INVALID_SHELL_OPENINGS','Opening-face intents must be distinct',identity)


def selected(options,inventory,identity):
    indices=[resolve(intent,inventory,identity+'.openings['+str(n)+']')['index'] for n,intent in enumerate(options['openings'])]
    if len(set(indices))!=len(indices):fail('INVALID_SHELL_OPENINGS','Opening intents resolve to the same face',identity)
    return ['Face'+str(index) for index in indices]


def settings(options):
    return {'thickness':options['thickness'],'mode':'Skin',
        'join':'Intersection' if options['corners']=='sharp' else 'Arc',
        'reversed':options['side']=='inward','intersectionHandling':options['intersectionHandling']}
