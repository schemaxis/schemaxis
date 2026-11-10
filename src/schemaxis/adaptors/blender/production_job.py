"""Scene-production authoring without requiring a mesh DAG or placeholder node.

Lowering is application-owned, deterministic and uses the existing executor.
Original authored input, schema and route provenance remain the public contract.
"""
import copy
from schemaxis.errors import fail,keys
from schemaxis.pipeline import name
from schemaxis.schema import NAME,object_schema,arguments_schema
from schemaxis.camera import CAMERA
from .settings import RENDER_OPTIONS

VERSION='schemaxis.blender.production/1'


def document_schema():
    from .production import schema
    return object_schema({'version':{'const':VERSION},'id':{**NAME,'default':'main'},'production':schema(),
        'visible':{'type':'array','items':NAME,'minItems':1,'uniqueItems':True},
        'render':arguments_schema(RENDER_OPTIONS),'prepareOnly':{'type':'boolean','default':False},
        'size':{'type':'array','items':{'type':'integer','minimum':32,'maximum':2048},'minItems':2,'maxItems':2,'default':[320,240]},
        'cameras':{'type':'array','minItems':1,'maxItems':1000,'items':arguments_schema(CAMERA)},
        'maxPublications':{'type':'integer','minimum':1,'default':10000}},['version','production'])


def lower(document):
    keys(document,('version','id','production','visible','render','prepareOnly','size','cameras','maxPublications'),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','expected '+VERSION)
    identity=document.get('id','main');name(identity,'$.id')
    production=document.get('production')
    if not isinstance(production,dict):fail('INVALID_PRODUCTION','production must be an object','$.production')
    for field in ('objects','assets','materialGraphs','surfaceMaterials'):
        if field in production and not isinstance(production[field],list):fail('INVALID_PRODUCTION','production collections must be arrays','$.production.'+field)
    reserved={o.get('id') for o in production.get('objects',[]) if isinstance(o,dict) and isinstance(o.get('id'),str)}|{a.get('id') for a in production.get('assets',[]) if isinstance(a,dict) and isinstance(a.get('id'),str)}|{g.get('id') for g in production.get('materialGraphs',[]) if isinstance(g,dict) and isinstance(g.get('id'),str)}
    reserved|={g.get('id') for g in production.get('surfaceMaterials',[]) if isinstance(g,dict) and isinstance(g.get('id'),str)}
    anchor='SXProductionMaterial'
    while anchor in reserved:anchor+='X'
    from .production import validate
    production=validate(production,{anchor:{'filter':'material'}},where='$.production')
    visible=document.get('visible')
    if visible is None:
        visible=[a.get('id') for a in production.get('assets',[]) if isinstance(a,dict)]+[o.get('id') for o in production.get('objects',[]) if isinstance(o,dict) and o.get('kind') in ('mesh','curve','spline','text','instance','collectionInstance')]
    if not visible:fail('INVALID_SCENE','production needs at least one geometric asset or explicit visible root','$.visible')
    lowered={'version':'schemaxis.blender/1','nodes':[{'id':anchor,'filter':'material'}],
        'scenes':[{'id':identity,'visible':copy.deepcopy(visible),'production':copy.deepcopy(production),
            'render':copy.deepcopy(document.get('render',{})),'prepareOnly':document.get('prepareOnly',False),
            'images':[{'id':'preview','size':copy.deepcopy(document.get('size',[320,240])),
                       'cameras':copy.deepcopy(document.get('cameras',[{'direction':[1,-2,1]}]))}]}]}
    if 'maxPublications' in document:lowered['maxPublications']=document['maxPublications']
    return lowered
