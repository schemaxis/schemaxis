"""Internal pointed-tool intent and conservative declared-envelope admission.

Not registered by the public CAM route until native/source/material qualification
is complete. The original flat-tool compiler and plan identities are unchanged.
"""
import json
import math
import uuid

from schemaxis.errors import fail, keys
from schemaxis.pipeline import name
from .cam_drilling import number, locations, compile_cycle

# Existing posted NC uses eight decimal places. This is its prospective word
# rounding bound, not a new geometric comparison tolerance.
WORD_ROUNDING = .505e-8
# The fixed 1.1.4 builtin endmill.fcstd Sketch constraint 20 is a 0.01 mm
# axial overlap. With a wider shank its transition occupies material below the
# declared cutting-height plane. Native physical readback must bind this exact
# profile as well; this constant is not a fitted clearance/tolerance margin.
ENDMILL_SHANK_OVERLAP = .01


def clearance(raw, path='$.setup.toolClearance'):
    if isinstance(raw,dict) and raw.get('kind')=='evolvingStock':
        keys(raw,('kind','minimumSeparation'),path)
        gap=number(raw.get('minimumSeparation'),path+'.minimumSeparation',0,1000)
        if gap<=0:
            fail('INVALID_MACHINING','Declare positive separation for the complete noncutting bit and holder',path+'.minimumSeparation')
        return {'kind':'evolvingStock','minimumSeparation':gap}
    keys(raw, ('kind', 'axialClearance'), path)
    if raw.get('kind') != 'aboveBlank':
        fail('INVALID_MACHINING', 'Choose aboveBlank or evolvingStock physical clearance semantics', path+'.kind')
    gap = number(raw.get('axialClearance'), path+'.axialClearance', 0, 1000)
    if gap <= 0:
        fail('INVALID_MACHINING', 'Declare a positive engineering axial clearance above the original blank', path+'.axialClearance')
    return {'kind': 'aboveBlank', 'axialClearance': gap}


def holder(raw, cutting_reach, length, bit_radius, path):
    """Contiguous outer envelope; insertion overlaps the non-cutting bit."""
    keys(raw, ('stickOut', 'steps'), path)
    stick_out = number(raw.get('stickOut'), path+'.stickOut', .1, 2000)
    if not cutting_reach <= stick_out < length:
        fail('INVALID_MACHINING', 'Holder stick-out must follow the cutting region and leave positive bit insertion', path+'.stickOut')
    steps = raw.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        fail('INVALID_MACHINING', 'Declare one to eight contiguous holder steps', path+'.steps')
    result = []
    lengths = []
    for index, item in enumerate(steps):
        here = path+'.steps['+str(index)+']'
        keys(item, ('diameter', 'length'), here)
        radius = number(item.get('diameter'), here+'.diameter', .1, 500)/2
        span = number(item.get('length'), here+'.length', .1, 2000)
        start = stick_out+math.fsum(lengths)
        lengths.append(span)
        end = stick_out+math.fsum(lengths)
        if end > 4000 or end <= start:
            fail('RESOURCE_LIMIT', 'Holder axial extent exceeds its finite envelope', here)
        if start < length and radius < bit_radius:
            fail('INVALID_MACHINING', 'Every holder step overlapping the inserted bit must enclose its radius', here+'.diameter')
        result.append({'start': start, 'end': end, 'radius': radius})
    if result[-1]['end'] < length:
        fail('INVALID_MACHINING', 'The holder envelope must cover the inserted bit end', path+'.steps')
    return {'stickOut': stick_out, 'steps': result}


def tool(raw, index, path):
    if type(index) is not int or not 0 <= index < 8:
        fail('RESOURCE_LIMIT', 'The compiled tool table contains at most eight tools', path)
    keys(raw, ('id', 'kind', 'diameter', 'tipAngle', 'cuttingReach', 'length',
               'flutes', 'rpm', 'feed', 'plunge', 'holder', 'shankDiameter'), path)
    identity = name(raw.get('id'), path+'.id')
    if raw.get('kind') != 'drill':
        fail('UNSUPPORTED_TOOL', 'This finite tool compiler requires a pointed drill', path+'.kind')
    values = {key: number(raw.get(key, default), path+'.'+key, low, high)
              for key, default, low, high in (
                  ('diameter', None, .1, 100), ('tipAngle', None, 1, 179),
                  ('cuttingReach', None, .1, 1000), ('length', None, .1, 2000),
                  ('flutes', 2, 1, 12), ('rpm', None, 1, 100000),
                  ('feed', None, .01, 100000), ('plunge', None, .01, 100000))}
    if int(values['flutes']) != values['flutes']:
        fail('INVALID_MACHINING', 'Flute count must be an integer', path+'.flutes')
    values['flutes'] = int(values['flutes'])
    h = values['diameter']/2/math.tan(math.radians(values['tipAngle']/2))
    if not math.isfinite(h) or not 0 < h < values['cuttingReach'] < values['length']:
        fail('UNSUPPORTED_TOOL_REACH', 'The cone junction must precede the declared cutting end and physical bit end', path)
    values['tipHeight'] = h
    if 'shankDiameter' in raw:
        shank=number(raw['shankDiameter'],path+'.shankDiameter',.1,values['diameter'])
        if shank>=values['diameter']:
            fail('INVALID_MACHINING','Declare a smaller reduced shank, or omit shankDiameter for the standard drill',path+'.shankDiameter')
        values['shankDiameter']=shank
    if 'holder' in raw:
        values['holder'] = holder(raw['holder'], values['cuttingReach'], values['length'],
                                  values.get('shankDiameter',values['diameter'])/2, path+'.holder')
    marker = json.dumps({'id': identity, 'kind': 'drill', 'geometry': {
        key: value for key, value in values.items() if key not in ('rpm', 'feed', 'plunge')}},
        sort_keys=True, separators=(',', ':'))
    return {'id': identity, 'kind': 'drill', **values, 'number': index+1,
            'controller': 'Cutter'+str(index), 'nativeTool': 'DrillTool'+str(index),
            'nativeId': str(uuid.uuid5(uuid.NAMESPACE_URL, 'schemaxis.freecad.cam.tools/1/'+marker))}


def flat_tool(raw, index, setup, path):
    """Opt-in short/wide-shank intent; the old default compiler is untouched."""
    from . import cam_tools
    if type(index) is not int or not 0 <= index < 8:
        fail('RESOURCE_LIMIT', 'The compiled tool table contains at most eight tools', path)
    if 'toolClearance' not in setup:
        fail('UNSUPPORTED_TOOL_REACH', 'Short or wide-shank tools need an explicit qualified clearance policy', '$.setup.toolClearance')
    clearance(setup['toolClearance'])
    keys(raw, ('id', 'kind', *cam_tools.GEOMETRY, *cam_tools.CUTTING, 'holder'), path)
    identity = name(raw.get('id'), path+'.id')
    if raw.get('kind') != 'flatEndmill':
        fail('UNSUPPORTED_TOOL', 'This finite tool compiler requires a flatEndmill', path+'.kind')
    values = {key: number(raw.get(key, default), path+'.'+key, low, high)
              for key, default, low, high in (
                  ('diameter', None, .1, 100), ('cuttingLength', None, .1, 1000),
                  ('length', None, .1, 2000), ('shankDiameter', None, .1, 100),
                  ('flutes', 2, 1, 12), ('rpm', None, 1, 100000),
                  ('feed', None, .01, 100000), ('plunge', None, .01, 100000))}
    if int(values['flutes']) != values['flutes']:
        fail('INVALID_MACHINING', 'Flute count must be an integer', path+'.flutes')
    values['flutes'] = int(values['flutes'])
    if values['length'] <= values['cuttingLength']:
        fail('UNSUPPORTED_TOOL_REACH', 'Physical bit length must exceed its cutting length', path)
    values['noncuttingStart'] = values['cuttingLength']-(
        ENDMILL_SHANK_OVERLAP if values['shankDiameter'] > values['diameter'] else 0)
    if 'holder' in raw:
        values['holder'] = holder(raw['holder'], values['cuttingLength'], values['length'],
                                  max(values['diameter'], values['shankDiameter'])/2, path+'.holder')
    return cam_tools.compiled(identity, values, index)


def source_regime(apex, junction, base, top):
    """Geometric intervals to measure, not permission to infer absent faces."""
    cone = [max(apex, base), min(junction, top)]
    cylinder = [max(junction, base), top]
    if junction <= base:
        kind = 'through'
    elif apex < base:
        kind = 'clippedCone'
    elif junction > top:
        kind = 'spot'
    else:
        kind = 'blind'
    return {'frame': 'source', 'kind': kind, 'cone': cone if cone[0] < cone[1] else None,
            'cylinder': cylinder if cylinder[0] < cylinder[1] else None}


def operation(raw, selected_tool, bounds, origin, setup, path):
    """Physical apex drives NC/material; the authored reference stays explicit."""
    keys(raw, ('id', 'operation', 'tool', 'locations', 'bottom', 'depthReference',
               'throughClearance', 'cycle'), path)
    if 'toolClearance' not in setup:
        fail('UNSUPPORTED_TOOL_REACH', 'Pointed drilling requires an explicit qualified tool-clearance policy', '$.setup.toolClearance')
    clearance(setup['toolClearance'])
    mode = raw.get('depthReference')
    if mode not in ('tip', 'fullDiameter'):
        fail('INVALID_MACHINING', 'Choose tip or fullDiameter bottom semantics', path+'.depthReference')
    bottom = number(raw.get('bottom'), path+'.bottom')
    h = selected_tool['tipHeight']
    apex = bottom if mode == 'tip' else bottom-h
    junction = bottom if mode == 'fullDiameter' else apex+h
    if not math.isfinite(apex) or not math.isfinite(junction) or not apex < bounds[5]:
        fail('INVALID_MACHINING', 'The physical drill tip must enter the source stock', path+'.bottom')
    if mode == 'fullDiameter' and bottom > bounds[5]:
        fail('INVALID_MACHINING', 'A full-diameter bottom cannot be above the source top', path+'.bottom')
    allowance = None
    if 'throughClearance' in raw:
        allowance = number(raw['throughClearance'], path+'.throughClearance', 0, 1000)
        if allowance <= 0:
            fail('INVALID_MACHINING', 'Below-stock clearance must be explicitly positive', path+'.throughClearance')
    if apex < bounds[4] and (allowance is None or apex < bounds[4]-allowance):
        fail('UNSUPPORTED_HOLDING', 'A below-stock physical tip requires enough explicit throughClearance', path+'.throughClearance')
    points = locations(raw.get('locations'), path+'.locations')
    # A cone-only spot has a smaller in-stock opening than its full tool radius.
    # Above-stock tool material belongs to the separate envelope policy.
    radius = selected_tool['diameter']/2
    opening = min(radius, (bounds[5]-apex)*radius/h)
    if any(not (bounds[0]+opening < x < bounds[1]-opening and
                bounds[2]+opening < y < bounds[3]-opening) for x, y in points):
        fail('INVALID_MACHINING', 'The actual in-stock opening must lie inside the pre-sized blank', path+'.locations')
    finish = apex-origin[2]
    result = {'locations': points, 'centres': [[x-origin[0], y-origin[1]] for x, y in points],
              'bottom': bottom, 'depthReference': mode, 'start': bounds[5]-origin[2],
              'finish': finish, 'nativeFinish': bottom-origin[2],
              'extraOffset': 'None' if mode == 'tip' else 'Drill Tip',
              'junction': junction-origin[2], 'sourceRegime': source_regime(apex, junction, bounds[4], bounds[5]),
              'cycle': compile_cycle(raw.get('cycle', {}), finish, setup, path+'.cycle')}
    if allowance is not None:
        result['throughClearance'] = allowance
    return result


def admit_tip_clearance(plan, replay=None):
    """Bind a pointed tip's whole rounding interval to its below-stock gap."""
    known = {t['id']: t for t in plan['tools']}
    base = plan['stockBounds'][4]
    specs = [op for op in plan['operations'] if op['operation'] == 'drill']
    if replay is not None and len(replay['cycles']) != sum(len(op['centres']) for op in specs):
        fail('VERIFICATION_FAILED', 'Tip clearance needs every actual source-bound drilling cycle')
    offset = 0
    for spec in specs:
        count = len(spec['centres'])
        cycles = None if replay is None else replay['cycles'][offset:offset+count]
        offset += count
        if known[spec['tool']]['kind'] != 'drill':
            continue
        plane = base-spec.get('throughClearance', 0)
        values = [spec['finish']] if cycles is None else [cycle['bottom'] for cycle in cycles]
        for tip in values:
            lower = math.nextafter(tip-WORD_ROUNDING, -math.inf)
            if not math.isfinite(lower) or lower < plane:
                fail('UNSUPPORTED_HOLDING', 'The pointed tip rounding interval crosses the declared below-stock clearance plane',
                     spec['id'], minimumTipZ=lower, permittedTipPlane=plane)
    return True


def noncutting_start(selected_tool):
    reach = (selected_tool['cuttingReach'] if selected_tool['kind'] == 'drill'
             else selected_tool['noncuttingStart'])
    starts = [reach]
    if 'holder' in selected_tool:
        starts.extend(step['start'] for step in selected_tool['holder']['steps'])
    return min(starts)


def admit_reach(plan, replay=None, *, actual_starts=None):
    """Conservative ORIGINAL-blank plane proof; never use final removed stock."""
    policy = plan['setup']['toolClearance']
    if policy['kind'] != 'aboveBlank':
        fail('INVALID_MACHINING', 'Unknown compiled tool-envelope policy')
    known = {t['id']: t for t in plan['tools']}
    # Only fresh trusted native geometry may supply this refinement. A saved
    # readback/receipt is never an authority for reducing the physical envelope.
    if actual_starts is not None and (not isinstance(actual_starts, dict) or
            actual_starts.keys() != known.keys() or any(type(z) not in (int, float) or
            not math.isfinite(z) or z <= 0 for z in actual_starts.values())):
        fail('VERIFICATION_FAILED', 'Fresh physical tool-envelope measurements must cover every declared tool')
    lows = {}
    if replay is None:
        for op in plan['operations']:
            lows[op['tool']] = min(op['finish'], lows.get(op['tool'], math.inf))
    else:
        for motion in replay['motions']:
            identity = motion.get('tool')
            if identity not in known:
                fail('INVALID_NC', 'Every admitted motion needs its declared tool envelope')
            z = min(motion['from'][2], motion['to'][2])
            lows[identity] = min(z, lows.get(identity, math.inf))
    checked = []
    top = plan['stockBounds'][5]
    for identity, z in lows.items():
        tool_spec = known[identity]
        start = noncutting_start(tool_spec)
        if actual_starts is not None:
            start = min(start, actual_starts[identity])
        lower = math.nextafter(z+start-WORD_ROUNDING, -math.inf)
        if not math.isfinite(lower) or lower < top+policy['axialClearance']:
            fail('UNSUPPORTED_TOOL_REACH', 'Non-cutting bit or holder enters the declared gap above the original allowance-inclusive blank', identity,
                 minimumNoncuttingZ=lower, originalBlankTop=top, axialClearance=policy['axialClearance'])
        checked.append({'tool': identity, 'minimumTip': z, 'minimumNoncuttingZ': lower})
    return {'policy': policy, 'originalBlankTop': top, 'checked': checked,
            'initialStateBoundary': 'afterProgrammedClearancePositioning'}
