"""Native Sheet construction from the host's closed typed engineering table."""
from . import spreadsheet as policy, parameters
from schemaxis.errors import fail


def create(doc, prepared):
    import Spreadsheet  # Registers the installed native Sheet type.
    table = prepared['spreadsheet']
    obj = doc.addObject('Spreadsheet::Sheet', parameters.OBJECT_NAME)
    obj.Label = policy.LABEL
    obj.Visibility = False
    content = policy.contents(table)
    obj.set('A1',"'"+content['A1'])
    obj.set('B1',"'"+content['B1'])
    def cell(alias):
        address = table['cells'][alias]
        obj.set('A'+address[1:],"'"+content['A'+address[1:]])
        obj.set(address,content[address])
        obj.setAlias(address,parameters.property_name(alias))
        obj.setDisplayUnit(address,table['inputs'][alias]['unit'] if alias in table['inputs'] else 'mm')
    for alias in table['inputs']:cell(alias)
    doc.recompute()
    # Alias properties must exist before parsing dependent expressions. A later
    # alias assignment does not repair an already unresolved Sheet expression.
    for alias in table['formulas']:
        cell(alias)
        doc.recompute()
    for alias in table['cells']:
        if obj.getTypeIdOfProperty(parameters.property_name(alias)) != 'Spreadsheet::PropertySpreadsheetQuantity':
            fail('PARAMETER_ASSIGNMENT_FAILED', 'Spreadsheet cell is not a native unitful quantity', alias)
    return obj



def observe(obj, prepared):
    result = {'properties':{name:obj.getTypeIdOfProperty(name) for name in obj.PropertiesList},
              'cells':{address:{'contents':obj.getContents(address),'alias':obj.getAlias(address),
                                'displayUnit':obj.getDisplayUnit(address)} for address in obj.getUsedCells()}}
    policy.verify_native(prepared,result)
    return result
