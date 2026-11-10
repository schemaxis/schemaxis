"""Typed, unitful engineering tables; compile formulas without authored native code."""
import math
import re
from schemaxis.errors import fail, keys
from . import parameters

UNITS = {'mm': 1, 'cm': 10, 'm': 1000, 'in': 25.4}
LABEL = 'Design spreadsheet'
PERSISTENT = {'ExpressionEngine':'App::PropertyExpressionEngine','Label':'App::PropertyString',
              'Label2':'App::PropertyString','Visibility':'App::PropertyBool',
              'cells':'Spreadsheet::PropertySheet','columnWidths':'Spreadsheet::PropertyColumnWidths',
              'rowHeights':'Spreadsheet::PropertyRowHeights'}
QUANTITY_TYPE = 'Spreadsheet::PropertySpreadsheetQuantity'
LENGTH_UNIT = 'Unit: mm (1,0,0,0,0,0,0,0) [Length]'


def quantity(raw, location, *, zero=False):
    keys(raw, ('value', 'unit'), location)
    if set(raw) != {'value', 'unit'} or not isinstance(raw.get('unit'), str) or raw['unit'] not in UNITS:
        fail('INVALID_SPREADSHEET', 'Declare a numeric length and unit mm, cm, m or in', location)
    value = parameters.numeric(raw['value'], location+'.value')
    result = value * UNITS[raw['unit']]
    if not math.isfinite(result) or abs(result) > 100000 or (not zero and result <= 0):
        fail('INVALID_SPREADSHEET', 'Length must be positive and at most 100000 mm', location)
    return result


def prepare(raw):
    """Return a deterministic table and independently bounded affine cell values."""
    keys(raw, ('inputs', 'formulas'), '$.spreadsheet')
    inputs, formulas = raw.get('inputs'), raw.get('formulas', {})
    if (not isinstance(inputs, dict) or not inputs or not isinstance(formulas, dict)
            or not 1 <= len(inputs)+len(formulas) <= 32):
        fail('INVALID_SPREADSHEET', 'Use 1 to 32 named cells, including at least one independent input', '$.spreadsheet')
    if set(inputs) & set(formulas):
        fail('INVALID_SPREADSHEET', 'Each cell alias must be unique across inputs and formulas', '$.spreadsheet')
    for alias in [*inputs, *formulas]:
        if not isinstance(alias, str) or re.fullmatch(parameters.NAME_PATTERN, alias) is None:
            fail('INVALID_SPREADSHEET', 'Aliases start with a letter and contain at most 64 letters, digits or underscores', '$.spreadsheet')
    canonical_inputs, params, flattened = {}, {}, {}
    for alias, item in sorted(inputs.items()):
        where = '$.spreadsheet.inputs.'+alias
        keys(item, ('value', 'minimum', 'maximum', 'unit'), where)
        if set(item) != {'value', 'minimum', 'maximum', 'unit'}:
            fail('INVALID_SPREADSHEET', 'Inputs require value, minimum, maximum and unit', where)
        converted = {k: quantity({'value': item[k], 'unit': item['unit']}, where+'.'+k)
                     for k in ('value', 'minimum', 'maximum')}
        # Reuse the established positive native driver range/storage admission.
        params[alias] = parameters.prepare({alias: {'kind':'length', **converted}})[alias]
        canonical_inputs[alias] = dict(item)
        flattened[alias] = {'terms': {alias: 1}, 'offset': 0}
    pending = {}
    for alias, item in sorted(formulas.items()):
        where = '$.spreadsheet.formulas.'+alias
        keys(item, ('terms', 'offset'), where)
        terms = item.get('terms')
        if not isinstance(terms, dict) or not 1 <= len(terms) <= 4:
            fail('INVALID_SPREADSHEET', 'Formulas use 1 to 4 named length terms', where+'.terms')
        canonical = {}
        for source, coefficient in terms.items():
            if source not in inputs and source not in formulas:
                fail('INVALID_SPREADSHEET', 'Formula refers to an undeclared alias', where+'.terms.'+str(source))
            parameters.numeric(coefficient, where+'.terms.'+source)
            if not 0 < abs(coefficient) <= 1000000:
                fail('INVALID_SPREADSHEET', 'Use nonzero coefficients with magnitude at most 1000000', where)
            canonical[source] = coefficient
        offset = item.get('offset', {'value': 0, 'unit': 'mm'})
        quantity(offset, where+'.offset', zero=True)
        pending[alias] = {'terms': dict(sorted(canonical.items())), 'offset': dict(offset)}
    ordered = {}
    while pending:
        ready = [alias for alias, item in pending.items() if set(item['terms']) <= set(flattened)]
        if not ready:
            fail('SPREADSHEET_CYCLE', 'Spreadsheet formulas must form an acyclic dependency graph', '$.spreadsheet.formulas')
        for alias in ready:
            item = pending.pop(alias);where = '$.spreadsheet.formulas.'+alias
            contributions = {k: [] for k in inputs};offsets = [quantity(item['offset'], where+'.offset', zero=True)]
            for source, coefficient in item['terms'].items():
                for key, factor in flattened[source]['terms'].items():
                    contributions[key].append(coefficient*factor)
                offsets.append(coefficient*flattened[source]['offset'])
            try:
                terms = {key: math.fsum(values) for key, values in contributions.items() if values}
                terms = {key: value for key, value in terms.items() if value != 0}
                flat = {'terms': terms, 'offset': math.fsum(offsets)}
                if not terms or not all(math.isfinite(v) and abs(v) <= 1e12 for v in [*terms.values(), flat['offset']]):
                    raise ValueError('constant, nonfinite or excessive flattened formula')
            except (OverflowError, ValueError) as error:
                fail('INVALID_SPREADSHEET', 'Formula must retain an observable finite input dependency', where, detail=str(error))
            values = {k: v['value'] for k,v in params.items() if k in inputs}
            derived = {'kind':'length', 'value': parameters.evaluate(flat, values, where)}
            for minimum in (True, False):
                edge = {k: params[k]['minimum' if (c > 0) == minimum else 'maximum'] for k,c in terms.items()}
                derived['minimum' if minimum else 'maximum'] = parameters.evaluate(flat, edge, where)
            params[alias] = parameters.prepare({alias: derived})[alias]
            flattened[alias] = flat;ordered[alias] = item
    cells = {alias: 'B'+str(index+2) for index, alias in enumerate([*canonical_inputs, *ordered])}
    return {'inputs':canonical_inputs, 'formulas':ordered, 'cells':cells, 'expanded':flattened}, dict(sorted(params.items()))


def expand(binding, table):
    """Flatten driver aliases to independent inputs without losing correlation."""
    contributions = {key: [] for key in table['inputs']};offsets = [binding['offset']]
    for alias, coefficient in binding['terms'].items():
        for key, factor in table['expanded'][alias]['terms'].items():
            contributions[key].append(coefficient*factor)
        offsets.append(coefficient*table['expanded'][alias]['offset'])
    try:
        terms = {key: math.fsum(values) for key, values in contributions.items() if values}
        terms = {key: value for key, value in terms.items() if value != 0}
        result = {'terms':terms, 'offset':math.fsum(offsets)}
        if not all(math.isfinite(v) for v in [*terms.values(),result['offset']]):
            raise ValueError('nonfinite flattened binding')
        return result
    except (OverflowError, ValueError) as error:
        fail('INVALID_BINDING', 'Spreadsheet driver arithmetic is not finite', detail=str(error))


def check_used(table, bindings, params):
    """All rows must contribute, and independent inputs must alter real targets."""
    direct = {alias for binding in bindings for alias in binding['terms']}
    used = set(direct);pending = list(direct)
    while pending:
        alias = pending.pop()
        for source in table['formulas'].get(alias, {}).get('terms', {}):
            if source not in used:
                used.add(source);pending.append(source)
    if used != set(table['cells']):
        fail('UNUSED_SPREADSHEET_CELL', 'Every spreadsheet cell must contribute to a driven dimension', '$.spreadsheet')
    responsive = set()
    for binding in bindings:
        flat = expand(binding, table)
        scale = max(abs(parameters.evaluate(flat, {k: params[k]['minimum' if (c > 0) == low else 'maximum']
                    for k,c in flat['terms'].items()})) for low in (True,False))
        for alias, coefficient in flat['terms'].items():
            response = abs(coefficient*(params[alias]['maximum']-params[alias]['minimum']))
            if response > max(1e-6,1e-7*scale)*8:
                responsive.add(alias)
    if responsive != set(table['inputs']):
        fail('UNOBSERVABLE_BINDING', 'Every independent spreadsheet input must measurably alter a driven dimension across its bounds', '$.spreadsheet')


def formula(item):
    pieces = [format(value, '.17g')+' * '+parameters.property_name(alias)
              for alias,value in item['terms'].items()]
    offset = item['offset']
    return '='+' + '.join([*pieces, format(offset['value'], '.17g')+' '+offset['unit']])


def contents(table):
    result = {'A1':'Parameter', 'B1':'Length'}
    for alias, address in table['cells'].items():
        result['A'+address[1:]] = alias
        if alias in table['inputs']:
            item = table['inputs'][alias]
            result[address] = format(item['value'], '.17g')+' '+item['unit']
        else:
            result[address] = formula(table['formulas'][alias])
    return result


def schema():
    name = {'pattern':parameters.NAME_PATTERN}
    unit = {'type':'string', 'enum':list(UNITS)}
    number = {'type':'number', 'exclusiveMinimum':0, 'maximum':100000}
    offset = {'type':'object', 'additionalProperties':False,
              'properties':{'value':{'type':'number','minimum':-100000,'maximum':100000},'unit':unit},
              'required':['value','unit']}
    return {'type':'object','additionalProperties':False,'properties':{
        'inputs':{'type':'object','minProperties':1,'maxProperties':32,'propertyNames':name,
          'additionalProperties':{'type':'object','additionalProperties':False,'properties':{
              'value':number,'minimum':number,'maximum':number,'unit':unit},
              'required':['value','minimum','maximum','unit']}},
        'formulas':{'type':'object','maxProperties':31,'propertyNames':name,
          'additionalProperties':{'type':'object','additionalProperties':False,'properties':{
              'terms':{'type':'object','minProperties':1,'maxProperties':4,'propertyNames':name,
                'additionalProperties':{'type':'number','minimum':-1000000,'maximum':1000000,'not':{'const':0}}},
              'offset':offset},'required':['terms']}}},'required':['inputs']}


def verify_contents(table, observed, location='spreadsheet'):
    """Compare the finite compiled grammar, never evaluate submitted expression text."""
    if not isinstance(observed, dict) or set(observed) != set(contents(table)):
        fail('VERIFICATION_FAILED', 'Spreadsheet cell membership differs from typed intent', location)
    labels = {'A1':'Parameter','B1':'Length', **{'A'+cell[1:]:alias for alias,cell in table['cells'].items()}}
    for cell,text in labels.items():
        if observed[cell] != "'"+text:
            fail('VERIFICATION_FAILED', 'Spreadsheet row identity or header differs', location+'.'+cell)
    number = parameters.NUMBER
    quantity_pattern = re.compile(r'('+number+r') (mm|cm|m|in)')
    term_pattern = re.compile(r'('+number+r') \* dim_([A-Za-z][A-Za-z0-9_]{0,63})')
    def equal_quantity(text, expected):
        match = quantity_pattern.fullmatch(text)
        if match is None:return False
        # Quantity serialization may retain the authored unit or use base mm.
        value = float(match[1]);unit = match[2]
        if unit == expected['unit']:
            return value == parameters.expression_number(expected['value'])
        return unit == 'mm' and value == parameters.expression_number(expected['value']*UNITS[expected['unit']])
    for alias,cell in table['cells'].items():
        text = observed[cell]
        if not isinstance(text,str) or len(text)>2048:
            fail('VERIFICATION_FAILED', 'Spreadsheet cell content is missing or oversized', location+'.'+cell)
        if alias in table['inputs']:
            valid = text.startswith('=') and equal_quantity(text[1:], table['inputs'][alias])
        else:
            item = table['formulas'][alias]
            pieces = text[1:].split(' + ') if text.startswith('=') else []
            matches = [term_pattern.fullmatch(piece) for piece in pieces[:-1]]
            actual = [(m[2],float(m[1])) for m in matches if m is not None]
            expected = [(key,parameters.expression_number(value)) for key,value in item['terms'].items()]
            valid = (len(pieces)==len(expected)+1 and all(m is not None for m in matches)
                     and actual==expected and equal_quantity(pieces[-1],item['offset']))
        if not valid:
            fail('VERIFICATION_FAILED', 'Spreadsheet quantity or formula differs from typed intent', location+'.'+cell)



def native_properties(table):
    result = dict(PERSISTENT)
    for address in contents(table):
        result[address] = QUANTITY_TYPE if address in table['cells'].values() else 'App::PropertyString'
    return result


def verify_native(prepared, observed):
    table = prepared['spreadsheet']
    if (not isinstance(observed,dict) or set(observed)!={'properties','cells'}
            or observed['properties']!=native_properties(table) or not isinstance(observed['cells'],dict)
            or set(observed['cells'])!=set(contents(table))):
        fail('VERIFICATION_FAILED','Native spreadsheet properties or cells differ')
    texts = {}
    inverse = {cell:alias for alias,cell in table['cells'].items()}
    for cell,record in observed['cells'].items():
        if not isinstance(record,dict) or set(record)!={'contents','alias','displayUnit'}:
            fail('VERIFICATION_FAILED','Native spreadsheet cell observation is malformed',cell)
        alias = inverse.get(cell)
        expected_alias = parameters.property_name(alias) if alias else None
        expected_unit = (table['inputs'][alias]['unit'] if alias in table['inputs'] else 'mm') if alias else None
        if record['alias']!=expected_alias or record['displayUnit']!=expected_unit:
            fail('VERIFICATION_FAILED','Native spreadsheet alias or display unit differs',cell)
        texts[cell] = record['contents']
    verify_contents(table,texts)


def verify_xml(table, properties, location='spreadsheet'):
    """Bind all persistent cell state before any source document can be restored."""
    if {name:prop.get('type') for name,prop in properties.items()} != PERSISTENT:
        fail('VERIFICATION_FAILED','Saved spreadsheet persistent property membership differs',location)
    def child(name,tag,attrs):
        prop = properties[name]
        if len(prop)!=1 or prop[0].tag!=tag or prop[0].attrib!=attrs or len(prop[0]):
            fail('VERIFICATION_FAILED','Saved spreadsheet metadata differs',location+'.'+name)
    child('ExpressionEngine','ExpressionEngine',{'count':'0'})
    child('Label','String',{'value':LABEL})
    child('Label2','String',{'value':''})
    child('Visibility','Bool',{'value':'false'})
    child('columnWidths','ColumnInfo',{'Count':'0'})
    child('rowHeights','RowInfo',{'Count':'0'})
    prop = properties['cells']
    if len(prop)!=1 or prop[0].tag!='Cells':
        fail('VERIFICATION_FAILED','Saved spreadsheet cell container differs',location)
    cells = prop[0];expected = contents(table)
    if cells.attrib!={'Count':str(len(expected)),'xlink':'1'} or len(cells)!=len(expected)+1:
        fail('VERIFICATION_FAILED','Saved spreadsheet cell count or external-link metadata differs',location)
    xlinks = cells[0]
    if xlinks.tag!='XLinks' or xlinks.attrib!={'count':'0'} or len(xlinks):
        fail('VERIFICATION_FAILED','Saved spreadsheet has external links',location)
    texts = {};inverse={address:alias for alias,address in table['cells'].items()}
    for item in cells[1:]:
        address = item.get('address');alias = inverse.get(address)
        attrs = {'address','content'} | ({'displayUnit','alias'} if alias else set())
        if (item.tag!='Cell' or set(item.attrib)!=attrs or len(item) or address not in expected or address in texts
                or (alias and (item.get('alias')!=parameters.property_name(alias)
                    or item.get('displayUnit')!=(table['inputs'][alias]['unit'] if alias in table['inputs'] else 'mm')))):
            fail('VERIFICATION_FAILED','Saved spreadsheet cell, alias or display unit differs',location)
        texts[address] = item.get('content')
    verify_contents(table,texts,location)


# Fixed1.1.4 native roles. Bit0 is App::Property::Touched (Property.h), an
# execution-state flag that changes on ordinary recompute/save; all other bits
# govern persistence/editability and remain fixed for this compiled Sheet.
PROPERTY_STATUS = {'ExpressionEngine':67108864,'Label':134217728,'Label2':67108992,
                   'Visibility':648,'cells':67108864,'columnWidths':218103808,'rowHeights':218103808}


def verify_saved_object(table, obj, location='spreadsheet'):
    if (obj is None or obj.attrib!={'name':parameters.OBJECT_NAME}
            or len(obj)!=1 or obj[0].tag!='Properties'):
        fail('VERIFICATION_FAILED','Saved spreadsheet object has unexpected metadata or extensions',location)
    container=obj[0]
    if container.attrib!={'Count':'7','TransientCount':'0'} or len(container)!=7:
        fail('VERIFICATION_FAILED','Saved spreadsheet persistent/transient property inventory differs',location)
    properties={}
    for prop in container:
        name=prop.get('name');status=prop.get('status','')
        if (prop.tag!='Property' or name not in PERSISTENT or name in properties
                or set(prop.attrib)!={'name','type','status'} or prop.get('type')!=PERSISTENT[name]
                or re.fullmatch(r'(?:0|[1-9][0-9]{0,9})',status) is None
                or int(status)&~1!=PROPERTY_STATUS[name]):
            fail('VERIFICATION_FAILED','Saved spreadsheet property identity or native role differs',location)
        properties[name]=prop
    verify_xml(table,properties,location)
