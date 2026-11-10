# Copyright (C) 2026 David L F Gaden
"""Bounded native length drivers; authored expressions initialise each visit only."""
import math
import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile, BadZipFile
from .document_xml import ARCHIVE_ERRORS

from schemaxis.errors import fail, keys

NAME_PATTERN = r'^[A-Za-z][A-Za-z0-9_]{0,63}$'
OBJECT_NAME = 'SchemaxisParameters'
OBJECT_LABEL = 'Design parameters'
BASE_PROPERTIES = {'ExpressionEngine', 'Label', 'Label2', 'Visibility'}
TARGETS = {'box': {'length': 'Length', 'width': 'Width', 'height': 'Height'},
           'cylinder': {'radius': 'Radius', 'height': 'Height'},
           'extrude': {'length': 'LengthFwd'}, 'pad': {'length':'Length'}, 'pocket': {'length':'Length'},
           'rectangle':{'width':'.Constraints.width','height':'.Constraints.height'},
           'circle':{'radius':'.Constraints.radius'},'slot':{'length':'.Constraints.span','radius':'.Constraints.radius'}}
TARGETS.update({'hole':{'diameter':'Diameter','depth':'Depth','recessDiameter':'HoleCutDiameter','recessDepth':'HoleCutDepth'},'boltGrid':{'xPitch':'.Constraints.xPitch','yPitch':'.Constraints.yPitch'},'boltCircle':{'radius':'.Constraints.pitchRadius'}})
TARGETS['shell']={'thickness':'Value'}
TARGETS['arcPath']={'bendRadius':'.Constraints.bendRadius'}
for _helix in ('additiveHelix','subtractiveHelix'):
    TARGETS[_helix]={'pitch':'Pitch','height':'Height'}
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
TERM = re.compile(r'(' + NUMBER + r') \* SchemaxisParameters\.dim_([A-Za-z][A-Za-z0-9_]{0,63})')
OFFSET = re.compile(r'(' + NUMBER + r') mm')


def object_type(prepared):
    return 'Spreadsheet::Sheet' if 'spreadsheet' in prepared else 'App::VarSet'


def object_label(prepared):
    if 'spreadsheet' in prepared:
        from .spreadsheet import LABEL
        return LABEL
    return OBJECT_LABEL


def numeric(value, location):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        fail('INVALID_PARAMETER', 'Use a finite numeric length or coefficient', location)
    return value


def saved_length(value):
    # FreeCAD 1.1.x PropertyLength XML uses 16 fractional decimal places.
    return float(format(value, '.16f'))


def expression_number(value):
    # ExpressionEngine renders literals using 15 significant decimal digits.
    return float(format(value, '.15g'))


def property_name(identity):
    return 'dim_' + identity


def prepare(raw):
    if not isinstance(raw, dict) or not 1 <= len(raw) <= 32:
        fail('INVALID_PARAMETER', 'Provide 1 to 32 named native length parameters', '$.parameters')
    result = {}
    for identity, item in sorted(raw.items()):
        location = '$.parameters.' + str(identity)
        if not isinstance(identity, str) or not re.fullmatch(NAME_PATTERN, identity):
            fail('INVALID_PARAMETER', 'Parameter names start with a letter and use up to 64 letters, digits or underscores', location)
        keys(item, ('kind', 'value', 'minimum', 'maximum'), location)
        if set(item) != {'kind', 'value', 'minimum', 'maximum'} or item['kind'] != 'length':
            fail('INVALID_PARAMETER', 'Declare kind length, value, minimum and maximum in mm', location)
        low, high, value = (numeric(item[k], location + '.' + k) for k in ('minimum', 'maximum', 'value'))
        if not 0 < low < high <= 100000 or not low <= value <= high:
            fail('INVALID_PARAMETER', 'Require 0 < minimum < maximum <= 100000 mm, containing value', location)
        for field, number in (('minimum',low), ('maximum',high), ('value',value)):
            if saved_length(number) <= 0:
                fail('UNREPRESENTABLE_PARAMETER', 'The positive driver or bound rounds to zero in native FCStd storage; use a larger millimetre value', location+'.'+field)
        result[identity] = dict(item)
    return result


def evaluate(binding, values, location='$'):
    try:
        terms = [coefficient * values[identity] for identity, coefficient in binding['terms'].items()]
        if any(not math.isfinite(v) for v in terms):
            raise ValueError('nonfinite product')
        value = math.fsum([binding['offset'], *terms])
        if not math.isfinite(value):
            raise ValueError('nonfinite sum')
        return value
    except (OverflowError, ValueError) as error:
        fail('INVALID_BINDING', 'Affine arithmetic is nonfinite or exceeds numeric limits', location, detail=str(error))


def drive(node, parameters, used, *, spreadsheet=None):
    raw = node.get('drive')
    location = '$.nodes.' + str(node.get('id')) + '.drive'
    if not isinstance(raw, dict) or not raw:
        fail('INVALID_BINDING', 'drive must map supported length options to affine bindings', location)
    if not parameters:
        fail('INVALID_BINDING', 'Declare native parameters before using drive', location)
    allowed = TARGETS.get(node.get('filter'), {})
    options = node.get('options', {})
    if not isinstance(options, dict):
        fail('INVALID_BINDING', 'options must be an object', location)
    result = {}
    for option, binding in sorted(raw.items()):
        where = location + '.' + str(option)
        if option not in allowed:
            fail('INVALID_BINDING', 'Drive declared primitive, sketch, Pad or finite-depth Pocket length dimensions only', where)
        if option in options:
            fail('CONFLICTING_BINDING', 'Omit the driven option from options, even when its value agrees', where)
        keys(binding, ('terms', 'offset'), where)
        terms = binding.get('terms')
        if not isinstance(terms, dict) or not 1 <= len(terms) <= 4:
            fail('INVALID_BINDING', 'Use 1 to 4 declared parameter terms', where + '.terms')
        canonical = {}
        for identity, coefficient in sorted(terms.items()):
            if identity not in parameters:
                fail('INVALID_BINDING', 'Binding refers to an undeclared parameter', where + '.terms.' + str(identity))
            numeric(coefficient, where + '.terms.' + identity)
            if coefficient == 0 or abs(coefficient) > 1000000:
                fail('INVALID_BINDING', 'Coefficients must be nonzero and at most 1000000 in magnitude', where)
            canonical[identity] = coefficient
        offset = numeric(binding.get('offset', 0), where + '.offset')
        if abs(offset) > 1000000:
            fail('INVALID_BINDING', 'Offset magnitude must not exceed 1000000 mm', where)
        prepared = {'terms': canonical, 'offset': offset}
        interval = prepared
        if spreadsheet is not None:
            from .spreadsheet import expand
            interval = expand(prepared, spreadsheet)
        extrema = []
        for minimum in (True, False):
            values = {k: parameters[k]['minimum' if (c > 0) == minimum else 'maximum'] for k,c in interval['terms'].items()}
            extrema.append(evaluate(interval, values, where))
        if not 0 < extrema[0] <= extrema[1] <= 100000:
            fail('INVALID_BINDING', 'Every value across the declared independent parameter bounds must be a positive length <= 100000 mm', where)
        # A coefficient that vanishes numerically cannot establish a native relationship.
        for identity, coefficient in canonical.items():
            span = parameters[identity]['maximum'] - parameters[identity]['minimum']
            response = abs(coefficient * span)
            scale = max(abs(v) for v in extrema)
            if response == 0 or response <= max(1e-6, 1e-7 * scale) * 8:
                fail('UNOBSERVABLE_BINDING', 'Driver response across its bounds is too small to verify; enlarge its range or coefficient', where, parameter=identity)
        used.update(canonical)
        result[option] = prepared
    return result


def expression(binding, object_name=OBJECT_NAME):
    pieces = [format(c, '.17g') + ' * ' + object_name + '.' + property_name(k)
              for k,c in sorted(binding['terms'].items())]
    return ' + '.join([*pieces, format(binding['offset'], '.17g') + ' mm'])


def check_expression(text, binding, location, object_name=OBJECT_NAME):
    if not isinstance(text, str) or len(text) > 2048:
        fail('VERIFICATION_FAILED', 'Native expression is missing or oversized', location)
    pieces = text.split(' + ')
    term = TERM if object_name == OBJECT_NAME else re.compile(
        r'(' + NUMBER + r') \* ' + re.escape(object_name) + r'\.dim_([A-Za-z][A-Za-z0-9_]{0,63})')
    matches = [term.fullmatch(p) for p in pieces[:-1]]
    offset = OFFSET.fullmatch(pieces[-1])
    if offset is None or any(m is None for m in matches):
        fail('VERIFICATION_FAILED', 'Native expression is outside the compiled affine grammar', location)
    observed = [(m[2], float(m[1])) for m in matches]
    if observed != [(k,expression_number(v)) for k,v in sorted(binding['terms'].items())] or float(offset[1]) != expression_number(binding['offset']):
        fail('VERIFICATION_FAILED', 'Native expression coefficients, parameters or offset differ', location)


def expected_expressions(node):
    result = {TARGETS[node['filter']][option]: binding for option,binding in node.get('drive', {}).items()}
    if node['filter']=='bodySeed':result['Placement']=node['seed']['source']+'.Placement'
    from .drilling import PROFILES as drilling_profiles,expressions as drilling_expressions
    if node['filter'] in drilling_profiles:result.update(drilling_expressions(node['filter'],node['options']))
    if node['filter']=='slot':result['.Constraints.anchorX']='-.Constraints.span / 2'
    if node['filter'] == 'rectangle':
        result.update({'.Constraints.anchorX': '-.Constraints.width / 2',
                       '.Constraints.anchorY': '-.Constraints.height / 2'})
    return result


def check_engines(prepared, engines, auxiliaries=None):
    from .operations import extra_objects
    names = {'N'+str(i) for i in range(len(prepared['nodes']))} | set(extra_objects(prepared))
    if 'parameters' in prepared:names.add(OBJECT_NAME)
    extra=set()
    if 'partDesign' in prepared:
        from .part_design import verify_auxiliaries
        extra=set(verify_auxiliaries(prepared,auxiliaries))
        names.update(extra)
    if not isinstance(engines, dict) or set(engines) != names or ('parameters' in prepared and engines[OBJECT_NAME] != []):
        fail('VERIFICATION_FAILED', 'Native expression object membership differs')
    if any(engines[k] for k in extra):fail('VERIFICATION_FAILED','Body origin helpers have unexpected expressions')
    if any(engines[k] for k in extra_objects(prepared)):fail('VERIFICATION_FAILED','Refine outputs have unexpected expressions')
    for index,node in enumerate(prepared['nodes']):
        pairs = engines['N' + str(index)]
        if not isinstance(pairs, list) or any(not isinstance(p,list) or len(p)!=2 or any(not isinstance(v,str) for v in p) for p in pairs):
            fail('VERIFICATION_FAILED', 'Native expression assignments are malformed', node['id'])
        actual = dict(pairs)
        wanted = expected_expressions(node)
        if len(actual) != len(pairs) or set(actual) != set(wanted):
            fail('VERIFICATION_FAILED', 'Missing or extra native expression assignment', node['id'])
        for target,binding in wanted.items():
            if isinstance(binding,str):
                if actual[target] != binding:
                    fail('VERIFICATION_FAILED', 'Built-in sketch expression differs', node['id'])
            else:
                check_expression(actual[target], binding, node['id'] + '.' + target)


def quantity_agrees(actual, expected):
    # Native expression serialization uses15 significant digits. Bound arithmetic
    # readback to64 binary ULPs; this does not relax any geometry/export check.
    return (type(actual) in (int,float) and math.isfinite(actual)
            and abs(actual-expected)<=64*max(math.ulp(actual),math.ulp(expected),math.ulp(1.0)))


def verify_observation(prepared, observation, *, saved=False):
    sheet = 'spreadsheet' in prepared
    fields={'object','parameters','expressions','targets'}|({'auxiliaries'} if 'partDesign' in prepared else set())
    if sheet and not saved:fields.add('spreadsheet')
    if not isinstance(observation, dict) or set(observation) != fields:
        fail('VERIFICATION_FAILED', 'Native parameter observation is absent or malformed')
    params = prepared['parameters']
    if sheet:
        from . import spreadsheet
        expected_properties=sorted(spreadsheet.PERSISTENT)
        if not saved:spreadsheet.verify_native(prepared,observation['spreadsheet'])
    else:expected_properties=sorted(BASE_PROPERTIES | {property_name(k) for k in params})
    if observation['object'] != {'name':OBJECT_NAME, 'label':object_label(prepared), 'type':object_type(prepared), 'properties':expected_properties, 'visibility':False}:
        fail('VERIFICATION_FAILED', 'Native parameter object or property membership differs')
    if not isinstance(observation['parameters'], dict) or set(observation['parameters']) != set(params):
        fail('VERIFICATION_FAILED', 'Native parameter membership differs')
    for identity,param in params.items():
        observed = observation['parameters'][identity]
        wanted={'property','type','value'}|({'unit'} if sheet else set())
        if (not isinstance(observed, dict) or set(observed)!=wanted
                or observed['property']!=property_name(identity)
                or observed['type']!=('Spreadsheet::PropertySpreadsheetQuantity' if sheet else 'App::PropertyLength')
                or type(observed.get('value')) not in (int,float) or observed['value']<=0
                or (not quantity_agrees(observed['value'],param['value']) if sheet else observed['value'] not in (param['value'],saved_length(param['value'])))
                or (sheet and observed['unit']!=spreadsheet.LENGTH_UNIT)):
            fail('VERIFICATION_FAILED', 'Native parameter setting, type or readable name differs', identity)
    check_engines(prepared, observation['expressions'],observation.get('auxiliaries'))
    expected_targets = {node['id'] + '.' + option: node['options'][option]
                        for node in prepared['nodes'] for option in node.get('drive', {})}
    actual = observation['targets']
    if not isinstance(actual, dict) or set(actual) != set(expected_targets) or any(type(actual[k]) not in (int,float) or not math.isfinite(actual[k]) or not math.isclose(actual[k],v,rel_tol=1e-7,abs_tol=1e-6) for k,v in expected_targets.items()):
        fail('VERIFICATION_FAILED', 'Native bound length differs from the declared affine value')


def verify_saved(prepared, path):
    """Read parameter metadata and assignments from FCStd itself, without native imports."""
    try:
        from .document_xml import Document
        from .adaptor import DECLARATIONS
        xml=Document(path)
        from .operations import extra_objects
        expected_types={OBJECT_NAME:object_type(prepared),**{'N'+str(i):DECLARATIONS[n['filter']]['native'] for i,n in enumerate(prepared['nodes'])},
                        **extra_objects(prepared)}
        extra={}
        if 'partDesign' in prepared:
            from .part_design_saved import observation as body_observation
            extra['auxiliaries']=body_observation(prepared,xml)['auxiliaries']
            from .part_design import verify_auxiliaries
            expected_types.update(verify_auxiliaries(prepared,extra['auxiliaries']))
        if xml.types!=expected_types:raise ValueError('saved object membership or type differs')
        xml.string(OBJECT_NAME,'Label2')
        sheet='spreadsheet' in prepared
        if sheet:
            from . import spreadsheet
            spreadsheet.verify_saved_object(prepared['spreadsheet'],xml.root.find("./ObjectData/Object[@name='"+OBJECT_NAME+"']"))
            # Sheet quantities are native NoPersist properties. Their saved
            # authority is the exact checked cell grammar, not an invented cache.
            # Values below are the host evaluation of that bound typed graph;
            # actual native computed values are checked separately on both runs.
        observations={'object':{'name':OBJECT_NAME,'label':xml.string(OBJECT_NAME,'Label'),'type':xml.types[OBJECT_NAME],
            'properties':sorted(xml.properties[OBJECT_NAME]),'visibility':xml.boolean(OBJECT_NAME,'Visibility')},
            'parameters':{k:({'property':property_name(k),'type':'Spreadsheet::PropertySpreadsheetQuantity',
                              'value':v['value'],'unit':spreadsheet.LENGTH_UNIT} if sheet else
                             {'property':property_name(k),'type':xml.properties[OBJECT_NAME][property_name(k)].get('type'),
                              'value':xml.number(OBJECT_NAME,property_name(k))}) for k,v in prepared['parameters'].items()},
            'expressions':{name:xml.engine(name) for name in xml.types},'targets':{},**extra}
        for index,node in enumerate(prepared['nodes']):
            name='N'+str(index)
            if xml.string(name,'Label')!=node['id']:raise ValueError('saved feature label differs')
            for option in node.get('drive',{}):
                target=TARGETS[node['filter']][option]
                if target.startswith('.Constraints.'):value=xml.constraint(name,target.removeprefix('.Constraints.'))
                else:value=xml.number(name,target,'App::PropertyDistance' if node['filter']=='extrude' else 'App::PropertyLength')
                observations['targets'][node['id']+'.'+option]=value
        verify_observation(prepared,observations,saved=True)
        return observations
    except (OSError,ValueError,KeyError,AttributeError,TypeError,*ARCHIVE_ERRORS) as error:
        fail('VERIFICATION_FAILED','Saved native parameter definition is missing or invalid',str(path),detail=str(error))


def schema():
    length = {'type':'number','exclusiveMinimum':0,'maximum':100000}
    return {'type':'object','minProperties':1,'maxProperties':32,'propertyNames':{'pattern':NAME_PATTERN},
            'additionalProperties':{'type':'object','additionalProperties':False,
                'properties':{'kind':{'const':'length'},'value':length,'minimum':length,'maximum':length},
                'required':['kind','value','minimum','maximum']}}


def drive_schema(kind):
    binding = {'type':'object','additionalProperties':False,'properties':{
        'terms':{'type':'object','minProperties':1,'maxProperties':4,'propertyNames':{'pattern':NAME_PATTERN},
                 'additionalProperties':{'type':'number','minimum':-1000000,'maximum':1000000,'not':{'const':0}}},
        'offset':{'type':'number','minimum':-1000000,'maximum':1000000,'default':0}},'required':['terms']}
    return {'type':'object','minProperties':1,'additionalProperties':False,
            'properties':{option:binding for option in TARGETS.get(kind,{})}}
