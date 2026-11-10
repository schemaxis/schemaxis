"""Internal opt-in pointed/envelope compiler; no public route registration yet."""
import copy

from schemaxis.documents import resolve_document
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name
from .solid_source import source_record, vector
from .cam_drilling import number, operation as flat_drilling, DIALECT
from . import cam_pointed, cam_tools

VERSION = 'schemaxis.freecad.cam.plan/3'


def plan(document, *, captured=None, unread=False):
    document, _ = resolve_document(copy.deepcopy(document))
    keys(document, ('version', 'source', 'stock', 'tool', 'tools', 'operations',
                    'setup', 'quality', 'definitions', 'settings'), '$')
    if document.get('version') != 'schemaxis.freecad.cam/1':
        fail('UNSUPPORTED_VERSION', 'Expected schemaxis.freecad.cam/1')
    if ('tool' in document) == ('tools' in document):
        fail('INVALID_MACHINING', 'Declare either one flat tool or a named tools table', '$')
    source = source_record(document.get('source'), captured=captured, unread=unread)
    bounds = source['bounds']
    height = bounds[5]-bounds[4]
    raw = document.get('stock', {})
    keys(raw, ('top', 'sides', 'bottom'), '$.stock')
    stock = {k: number(raw.get(k, v), '$.stock.'+k, 0, 1000)
             for k, v in (('top', 2), ('sides', 0), ('bottom', 0))}
    if stock['sides'] or stock['bottom']:
        fail('UNSUPPORTED_HOLDING', 'Use a pre-sized blank with zero side and bottom allowance', '$.stock')
    origin = [(bounds[0]+bounds[1])/2, (bounds[2]+bounds[3])/2, bounds[5]+stock['top']]
    stock_bounds = [bounds[0]-origin[0], bounds[1]-origin[0], bounds[2]-origin[1],
                    bounds[3]-origin[1], bounds[4]-origin[2], 0]
    raw = document.get('setup', {})
    keys(raw, ('clearance', 'safe', 'toolClearance'), '$.setup')
    setup = {k: number(raw.get(k, v), '$.setup.'+k, .1, 1000)
             for k, v in (('clearance', 5), ('safe', 3))}
    setup['toolClearance'] = cam_pointed.clearance(raw.get('toolClearance'))
    if setup['clearance'] < setup['safe']:
        fail('INVALID_MACHINING', 'Clearance must be at or above the safe traverse plane', '$.setup')
    explicit = 'tools' in document
    raw_tools = document['tools'] if explicit else [document['tool']]
    if not isinstance(raw_tools, list) or not 1 <= len(raw_tools) <= 8:
        fail('INVALID_MACHINING', 'Declare one to eight named tools', '$.tools')
    tools = []
    for index, item in enumerate(raw_tools):
        path = '$.tools['+str(index)+']' if explicit else '$.tool'
        if not explicit:
            keys(item, (*cam_tools.GEOMETRY, *cam_tools.CUTTING, 'holder'), path)
            item = {'id': 'cutter', 'kind': 'flatEndmill', **item}
        if not isinstance(item, dict):
            fail('INVALID_MACHINING', 'Declare a typed physical tool', path)
        if item.get('kind') == 'drill':
            tool = cam_pointed.tool(item, index, path)
        else:
            tool = cam_pointed.flat_tool(item, index, setup, path)
        if any(t['id'] == tool['id'] for t in tools):
            fail('INVALID_MACHINING', 'Named tool identities must be unique', path+'.id')
        tools.append(tool)
    raw = document.get('quality', {})
    keys(raw, ('residualVolume', 'gougeVolume'), '$.quality')
    quality = {k: number(raw.get(k, v), '$.quality.'+k, 1e-5, 1)
               for k, v in (('residualVolume', .1), ('gougeVolume', .01))}
    raw = document.get('operations')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        fail('INVALID_MACHINING', 'Declare one to sixteen ordered machining operations', '$.operations')
    operations = []
    ids = set()
    faced = not stock['top']
    for index, item in enumerate(raw):
        path = '$.operations['+str(index)+']'
        if not isinstance(item, dict):
            fail('INVALID_MACHINING', 'Declare a typed machining operation', path)
        identity = name(item.get('id'), path+'.id')
        if identity in ids:
            fail('INVALID_MACHINING', 'Operation identities must be unique', path+'.id')
        ids.add(identity)
        tool = cam_tools.selected(tools, item, path, explicit=explicit)
        kind = item.get('operation')
        op = {'id': identity, 'operation': kind, 'tool': tool['id']}
        if kind == 'drill':
            if not faced:
                fail('INVALID_MACHINING', 'Face the top stock allowance before drilling', path)
            compile_drill = cam_pointed.operation if tool['kind'] == 'drill' else flat_drilling
            op.update(compile_drill(item, tool, bounds, origin, setup, path))
        elif kind in ('faceStock', 'pocket'):
            if tool['kind'] != 'flatEndmill':
                fail('UNSUPPORTED_TOOL', 'Pointed tools admit only qualified vertical drilling cycles', path+'.tool')
            keys(item, ('id', 'operation', 'tool', 'floor', 'stepDown', 'stepOver'), path)
            op.update(stepDown=number(item.get('stepDown', min(tool['diameter']/2, 2)),
                                     path+'.stepDown', .01, min(tool['diameter'], height+stock['top'])),
                      stepOver=number(item.get('stepOver', .5), path+'.stepOver', .05, .8))
            if kind == 'faceStock':
                if faced or index != 0 or 'floor' in item:
                    fail('INVALID_MACHINING', 'Face top allowance once before other cuts', path)
                op.update(start=0, finish=-stock['top'])
                faced = True
            else:
                if not faced:
                    fail('INVALID_MACHINING', 'Face top stock allowance before pocketing', path)
                floor = vector(item.get('floor'), 3, path+'.floor', code='INVALID_MACHINING')
                if (not bounds[4]+1e-5 < floor[2] < bounds[5]-1e-5 or
                        not bounds[0] < floor[0] < bounds[1] or not bounds[2] < floor[1] < bounds[3]):
                    fail('INVALID_MACHINING', 'Select an interior upward pocket floor above the clamping base', path+'.floor')
                op.update(floor=floor, start=-stock['top'], finish=floor[2]-origin[2])
        else:
            fail('INVALID_MACHINING', 'Choose faceStock, pocket or drill', path+'.operation')
        operations.append(op)
    cam_tools.require_used(tools, operations)
    prepared = {'version': VERSION, 'source': source, 'stock': stock, 'origin': origin,
                'stockBounds': stock_bounds, 'tools': tools, 'setup': setup, 'quality': quality,
                'operations': operations, 'postprocessor': 'linuxcnc', 'units': 'mm',
                'frame': 'stockTopCentre', 'cyclePolicy': DIALECT}
    if setup['toolClearance']['kind']=='aboveBlank':cam_pointed.admit_reach(prepared)
    # Evolving-stock access needs actual ordered native motion and complete
    # fresh physical masks; compilation does not publish clearance success.
    cam_pointed.admit_tip_clearance(prepared)
    return prepared
