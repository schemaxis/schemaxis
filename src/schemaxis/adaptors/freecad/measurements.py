"""Named geometric measurements as verified cross-adaptor value publications."""
import math
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from schemaxis.pipeline import name
from . import selections

QUANTITIES = {'volume':'mm^3', 'surfaceArea':'mm^2', 'extentX':'mm', 'extentY':'mm', 'extentZ':'mm',
              'centreOfMass':'mm', 'bounds':'mm', 'totalEdgeLength':'mm', 'edgeCount':'count'}
EDGE_QUANTITIES = ('totalEdgeLength', 'edgeCount')
DECLARATION = {'type':'array','minItems':1,'maxItems':32,'items':{'type':'object','properties':{
    'id':{'type':'string','required':True}, 'node':{'type':'string','required':True},
    'quantity':{'type':'enum','values':list(QUANTITIES),'required':True},
    'edges':{k:v for k,v in selections.EDGES.items() if k!='default'}}}}


def prepare(raw, kinds):
    result=validate_arguments({'measurements':DECLARATION},{'measurements':raw})['measurements']
    seen=set()
    for item in result:
        identity=name(item['id'],'measurements.id')
        if identity in seen:fail('DUPLICATE_MEASUREMENT','measurement ids must be distinct',identity)
        seen.add(identity)
        if item['node'] not in kinds or kinds[item['node']]!='solid':
            fail('INVALID_SELECTION','measurement must select a declared solid node',identity)
        if (item['quantity'] in EDGE_QUANTITIES) != ('edges' in item):
            fail('INVALID_MEASUREMENT','only edgeCount and totalEdgeLength require an edges selection',identity)
        if 'edges' in item:selections.validate(item['edges'],identity+'.edges')
    return result


def native_observations(doc, prepared, objects=None):
    from .native import snapshot
    requested=prepared.get('measurements',[])
    if objects is None:
        from .operations import output_names
        objects={identity:doc.getObject(name) for identity,name in output_names(prepared).items()}
    result={};edge_count=0
    for item in requested:
        identity=item['node']
        if identity not in result:
            shape=objects[identity].Shape
            # Finishing can return a Compound containing solids. Compounds do
            # not expose CenterOfMass; combine the constituent solid centres
            # with volume weights (uniform density, no material inference).
            solids=[(solid.Volume,list(solid.CenterOfMass)) for solid in shape.Solids]
            volume=math.fsum(weight for weight,_ in solids)
            if not solids or volume<=0:fail('INVALID_GEOMETRY','measurement source needs positive solid volume',identity)
            centre=[math.fsum(weight*point[i] for weight,point in solids)/volume for i in range(3)]
            result[identity]={'shape':snapshot(shape),'centreMM':centre}
        if 'edges' in item and 'edges' not in result[identity]:
            edges=selections.native_edges(objects[identity].Shape);edge_count+=len(edges)
            if edge_count>20000:fail('RESOURCE_BUDGET_EXCEEDED','measurement inventories exceed 20000 combined edges')
            result[identity]['edges']=edges
    return result


def evaluate(prepared, observations):
    requested=prepared.get('measurements',[])
    identities={item['node'] for item in requested}
    if not isinstance(observations,dict) or set(observations)!=identities:
        fail('VERIFICATION_FAILED','measurement source membership differs')
    edge_nodes={item['node'] for item in requested if 'edges' in item}
    total_edges=0
    for identity, record in observations.items():
        if set(record)!=({'shape','centreMM','edges'} if identity in edge_nodes else {'shape','centreMM'}):
            fail('VERIFICATION_FAILED','measurement observation members differ',identity)
        shape=record['shape']
        if (set(shape)!={'valid','solids','volume','area','bounds'} or shape['valid'] is not True
                or type(shape['solids']) is not int or shape['solids']<1):
            fail('VERIFICATION_FAILED','measurement source must be a valid solid',identity)
        for key in ('volume','area'):
            value=shape[key]
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
                fail('VERIFICATION_FAILED','invalid positive solid measure',identity,quantity=key)
        for value,length in ((shape['bounds'],6),(record['centreMM'],3)):
            if not isinstance(value,list) or len(value)!=length or any(type(v) not in (int,float) or not math.isfinite(v) for v in value):
                fail('VERIFICATION_FAILED','invalid measured coordinates',identity)
        b=shape['bounds']
        if any(b[i]>=b[i+1] for i in (0,2,4)):
            fail('VERIFICATION_FAILED','solid bounds must have positive extents',identity)
        if any(not b[2*i]-1e-6 <= value <= b[2*i+1]+1e-6 for i,value in enumerate(record['centreMM'])):
            fail('VERIFICATION_FAILED','centre of mass lies outside solid bounds',identity)
        if identity in edge_nodes:
            if not isinstance(record['edges'],list):fail('VERIFICATION_FAILED','measurement edge inventory is absent',identity)
            total_edges+=len(record['edges'])
    if total_edges>20000:fail('VERIFICATION_FAILED','measurement inventories exceed combined edge bound')
    result={}
    for item in requested:
        record=observations[item['node']];shape=record['shape'];quantity=item['quantity']
        entry={'node':item['node'],'quantity':quantity,'units':QUANTITIES[quantity]}
        if quantity=='volume':value=shape['volume']
        elif quantity=='surfaceArea':value=shape['area']
        elif quantity=='bounds':value=shape['bounds']
        elif quantity=='centreOfMass':value=record['centreMM']
        elif quantity.startswith('extent'):
            axis=2*'XYZ'.index(quantity[-1]);value=shape['bounds'][axis+1]-shape['bounds'][axis]
        else:
            indices=selections.resolve(item['edges'],record['edges'],item['id'])
            entry['selectedEdges']=indices
            value=len(indices) if quantity=='edgeCount' else math.fsum(record['edges'][i-1]['lengthMM'] for i in indices)
        entry['value']=value;result[item['id']]=entry
    return {'version':'schemaxis.freecad.measurements/1','coordinateUnits':'mm',
            'boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax'],
            'measurements':result,'scope':'native geometric measurements; centreOfMass assumes uniform density; no material, mass, clearance or manufacturing inference'}


def verify(prepared, built, reopened, publication):
    # Validate both observations before comparing or trusting a derived value.
    expected=evaluate(prepared,built);actual=evaluate(prepared,reopened)
    if not selections.equivalent(built,reopened) or not selections.equivalent(expected,actual):
        fail('VERIFICATION_FAILED','CAD measurements changed after reopening')
    if publication!=expected:fail('VERIFICATION_FAILED','published measurements differ from native evidence')
    return expected
