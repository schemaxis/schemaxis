# Copyright (C) 2026 David L F Gaden
"""Host-safe assemblies of verified phase-one Body parts joined at named mounts.

Each part definition names one verified single-Body ``model.FCStd`` publication
(directly or through a workflow ``$artifact`` index 2). The native build embeds
one editable copy of that part's complete history per definition, adds named
PartDesign coordinate-system mounts, then joins App::Link instances with real
fixed joints. A fixed joint makes the child mount frame coincide with the parent
mount frame after the parent-side offset and clocking:

    worldChild = worldParent * parentMount * T(offset) * Rz(clocking) * inverse(childMount)

This module never imports FreeCAD. Expected poses come from authored values and
producer receipts; native observations are judged against them, never the reverse.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import zipfile

from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name

PLAN_VERSION = 'schemaxis.freecad.assembly.plan/1'
SOURCE_NAME = 'model.FCStd'
SOURCE_BYTES = 64*1024*1024
RECEIPT_BYTES = 16*1024*1024
ZIP_MEMBERS = 4096
ZIP_EXPANDED = 512*1024*1024
# Whole-run budgets across every source definition (each also has the per-file limits).
TOTAL_SOURCE_BYTES = 128*1024*1024
TOTAL_EXPANDED_BYTES = 512*1024*1024
MAX_MOUNTS = 16
COORDINATE = 100000
AXES = {'+X': (1, 0, 0), '-X': (-1, 0, 0), '+Y': (0, 1, 0), '-Y': (0, -1, 0), '+Z': (0, 0, 1), '-Z': (0, 0, -1)}
OFFSET = {'type': 'array', 'items': {'type': 'number', 'minimum': -100000, 'maximum': 100000},
          'minItems': 3, 'maxItems': 3, 'default': [0, 0, 0]}
CLOCKING = {'type': 'number', 'minimum': -360, 'maximum': 360, 'default': 0}
FIXED_NAMES = ('Assembly', 'Joints', 'Ground')
# Labels FreeCAD gives its own objects; reusing one would make FreeCAD rename a label.
RESERVED_LABEL = re.compile(r'(?:Assembly|Joints|Ground|Origin|[XYZ]-axis|(?:XY|XZ|YZ)-plane)[0-9]*')


def is_sourced(document):
    parts = document.get('parts') if isinstance(document, dict) else None
    return isinstance(parts, list) and any(isinstance(p, dict) and 'source' in p for p in parts)


# ---------------------------------------------------------------- bounded files

def _plain(path, location, code='UNSUPPORTED_SOURCE'):
    """Refuse symbolic links anywhere in the path; the bytes must be what was named."""
    path = Path(path).absolute()
    if os.path.realpath(path) != str(path):
        fail(code, 'Paths must not contain symbolic links', location, path=str(path))
    return path


def _read(path, limit, location, *, code='UNSUPPORTED_SOURCE'):
    path = _plain(path, location)
    if not path.is_file():
        fail('RESOURCE_NOT_FOUND', 'Required source evidence is absent', location, path=str(path))
    if path.stat().st_size > limit:
        fail(code, 'Source evidence exceeds its size limit', location, path=str(path), limit=limit)
    return path.read_bytes()


def _json(path, location):
    try:
        return json.loads(_read(path, RECEIPT_BYTES, location).decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        fail('UNSUPPORTED_SOURCE', 'Source receipt is not valid JSON', location, path=str(path), detail=str(error))


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            hasher.update(block)
    return hasher.hexdigest()


def check_archive(path, location, *, code='UNSUPPORTED_SOURCE'):
    """Bound an FCStd ZIP before any XML is parsed from it."""
    path = _plain(path, location, code)
    if not path.is_file() or path.stat().st_size > SOURCE_BYTES:
        fail(code, 'FCStd archive is absent or exceeds 64 MiB', location, path=str(path))
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if (len(infos) > ZIP_MEMBERS or len(set(names)) != len(names) or names.count('Document.xml') != 1
                    or sum(i.file_size for i in infos) > ZIP_EXPANDED
                    or any(n.startswith('/') or '..' in n.split('/') or '\\' in n for n in names)):
                raise ValueError('archive membership, names or expanded size are outside the FCStd bounds')
            if archive.getinfo('Document.xml').file_size > 32*1024*1024:
                raise ValueError('Document.xml exceeds 32 MiB')
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        fail(code, 'FCStd archive is malformed or unbounded', location, path=str(path), detail=str(error))
    return path


# ------------------------------------------------------------------ admission

def _saved_exactly(prepared):
    """Numbers of a part plan that its saved document would not reproduce exactly.

    The producer's cached history is computed from in-memory values, but the saved
    document keeps lengths at 16 fractional digits and expression literals at 15
    significant digits. Any recompute (and the assembly build recomputes) then
    regenerates different history bytes, so such a source cannot be bound."""
    from .parameters import saved_length, expression_number
    found = []

    def leaves(where, value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            if saved_length(value) != value:
                found.append(where)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                leaves(f'{where}[{i}]', item)
        elif isinstance(value, dict):
            for key,item in value.items():
                leaves(f'{where}.{key}', item)
    for key, parameter in sorted(prepared.get('parameters', {}).items()):
        for field in ('value', 'minimum', 'maximum'):
            leaves(f'parameters.{key}.{field}', parameter[field])
    if 'spreadsheet' in prepared:
        table=prepared['spreadsheet']
        literals=[item['value'] for item in table['inputs'].values()]
        literals.extend(item['offset']['value'] for item in table['formulas'].values())
        literals.extend(value for item in table['formulas'].values() for value in item['terms'].values())
        if any(expression_number(value)!=value for value in literals):
            found.append('spreadsheet (expression literal precision)')
    for node in prepared['nodes']:
        for option, value in sorted(node['options'].items()):
            leaves(f"{node['id']}.{option}", value)
        for option, binding in sorted(node.get('drive', {}).items()):
            numbers = [binding['offset'], *binding['terms'].values()]
            if any(expression_number(n) != n for n in numbers):
                found.append(f"{node['id']}.{option} (expression)")
    return found


def admit(value, location):
    """Facts of one verified phase-one Body publication, from its own receipts."""
    from .adaptor import _native_plan as part_plan
    from .part_design import names as native_names
    if not isinstance(value, str) or not value or len(value) > 4096:
        fail('UNSUPPORTED_SOURCE', 'source must name a verified FreeCAD part model.FCStd', location)
    path = _plain(value, location)
    if path.name != SOURCE_NAME:
        fail('UNSUPPORTED_SOURCE', 'source must be the model.FCStd publication of a FreeCAD part run', location)
    if not path.is_file():
        fail('RESOURCE_NOT_FOUND', 'Source part file is absent', location, path=str(path))
    check_archive(path, location)
    run = path.parent
    authored = _json(run/'authored.json', location)
    if not isinstance(authored, dict) or authored.get('version') != 'schemaxis.freecad/1' or 'designStudy' in authored:
        fail('UNSUPPORTED_SOURCE', 'source must come from the schemaxis.freecad/1 part route (no design study)', location)
    planned = _json(run/'plan.json', location)
    try:
        if any(isinstance(n,dict) and n.get('filter')=='bodySeed' for n in authored.get('nodes',[])):
            from .source_bridge import EmbeddedSources
            prepared=part_plan(authored,source=EmbeddedSources(path,planned))
        else:prepared = part_plan(authored)
    except SchemaxisError as error:
        fail('UNSUPPORTED_SOURCE', 'source part input no longer plans', location, detail=error.fault.message)
    if planned != prepared:
        fail('UNSUPPORTED_SOURCE', 'source part plan differs from its authored input', location)
    inexact = _saved_exactly(prepared)
    if inexact:
        fail('UNSUPPORTED_SOURCE', 'Source part uses values its saved document cannot store exactly, so its stored '
             'history would not reproduce on recompute; re-run the part with values of at most 15 significant digits',
             location, values=inexact[:8])
    body = prepared.get('partDesign')
    generation=body.get('generation',1) if body else 1
    if generation==2:
        selected=body['owners'].get(prepared['output'])
        selected_record=body['bodies'].get(selected,{})
        if selected_record.get('tip')!=prepared['output'] or selected is None:
            fail('UNSUPPORTED_SOURCE','Source must publish a final solid Body tip',location)
        if not body.get('seeds') and {n['id'] for n in prepared['nodes']} != set(body['owners'])|set(body['bodies']):
            fail('UNSUPPORTED_SOURCE','Source histories must contain only their Bodies and owned members',location)
        selected_body={'body':selected,**selected_record}
    elif not body or body.get('tip') is None or prepared['output'] != body['tip']:
        fail('UNSUPPORTED_SOURCE', 'source must publish the solid tip of exactly one PartDesign Body', location)
    else:
        selected_body=body
    if generation!=2 and {n['id'] for n in prepared['nodes']} != set(body['members']) | {body['body']}:
        fail('UNSUPPORTED_SOURCE', 'source document contains geometry outside its Body', location)
    result = _json(run/'result.json', location)
    if not isinstance(result, dict) or result.get('verified') is not True or result.get('status') != 'succeeded':
        fail('UNSUPPORTED_SOURCE', 'source part run is not verified', location)
    receipt_path = run/'verification.json'
    receipt = _json(receipt_path, location)
    if not isinstance(receipt, dict):
        fail('UNSUPPORTED_SOURCE', 'source receipt is not an object', location)
    artifacts = receipt.get('artifacts')
    if (receipt.get('status') != 'succeeded' or receipt.get('units') != 'mm' or receipt.get('definition') != prepared
            or not isinstance(artifacts, list) or len(artifacts) < 3):
        fail('UNSUPPORTED_SOURCE', 'source receipt is incomplete or not in millimetres', location)
    publication = artifacts[2]
    if (not isinstance(publication, dict) or publication.get('file') != str(path) or publication.get('kind') != 'cadScene'
            or publication.get('units') != 'mm' or [a.get('file') for a in artifacts].count(str(path)) != 1):
        fail('UNSUPPORTED_SOURCE', 'source is not publication index 2 (cadScene, mm) of its receipt', location)
    sha256 = digest(path)
    if publication.get('sha256') != sha256:
        fail('INPUT_CHANGED', 'source part bytes differ from its verified receipt', location, path=str(path))
    native = receipt.get('native', {})
    from .body_seed import world_body
    if body.get('seeds') or world_body(prepared,prepared['output']) is not None:
        evidence=receipt.get('bodyLocalExportEvidence',{})
        selected_index=next(i for i,n in enumerate(prepared['nodes']) if n['id']==selected_body['body'])
        if evidence.get('frame')!='bodyLocal' or evidence.get('body')!='N'+str(selected_index):
            fail('UNSUPPORTED_SOURCE','Placed source receipt lacks its explicit Body-local geometry witness',location)
        native=evidence.get('shape',{})
    if (native.get('valid') is not True or native.get('solids') != 1 or not _finite(native.get('volume'))
            or native['volume'] <= 0 or not _finite(native.get('area')) or not _vector(native.get('bounds'), 6)):
        fail('UNSUPPORTED_SOURCE', 'source receipt lacks one valid positive-volume solid', location)
    mapped = native_names(prepared)
    observed = receipt.get('partDesignObservations', {})
    auxiliaries = observed.get('auxiliaries') if isinstance(observed, dict) else None
    from .part_design import verify_auxiliaries
    objects = {mapped[n['id']]: _native_type(n['filter']) for n in prepared['nodes']}
    from .operations import extra_objects
    objects.update(extra_objects(prepared))
    try:
        objects.update(verify_auxiliaries(prepared, auxiliaries))
    except SchemaxisError:
        fail('UNSUPPORTED_SOURCE', 'source receipt lacks its Body origin helpers', location)
    parameters = {}
    if 'parameters' in prepared:
        from .parameters import object_type
        objects['SchemaxisParameters'] = object_type(prepared)
        parameters = {k: {'value': v['value'], 'minimum': v['minimum'], 'maximum': v['maximum']}
                      for k, v in prepared['parameters'].items()}
    # Closed host envelope of the saved source, before anything could open it natively.
    from . import source_envelope
    sheet = {'spreadsheet':prepared['spreadsheet']} if 'spreadsheet' in prepared else {}
    from .source_bridge import record as bridge_record
    bridge=bridge_record(authored,prepared)
    envelope = source_envelope.inspect(path, {'objects': objects, 'parameters': parameters,'generation':generation,**sheet,**bridge}, location)
    if generation==2:
        from .part_design_saved import verify as verify_history
        verify_history(prepared,path)
        plane=auxiliaries[selected_body['body']]['XY_Plane']['name']
        profile_kind='designHistory'
    else:
        pad = next(n for n in prepared['nodes'] if n['filter'] == 'pad')
        profile_kind=next(n for n in prepared['nodes'] if n['id'] == pad['inputs']['profile'])['filter']
        plane=auxiliaries['XY_Plane']['name']
    return {'file': str(path), 'sha256': sha256, 'run': str(run), 'bytes': path.stat().st_size,
            'expandedBytes': envelope['expandedBytes'],
            'receiptSha256': hashlib.sha256(_read(receipt_path, RECEIPT_BYTES, location)).hexdigest(),
            'body': mapped[selected_body['body']], 'tip': mapped[selected_body['tip']],
            'members': [mapped[m] for m in selected_body['members']],
            'labels': {mapped[n['id']]: n['id'] for n in prepared['nodes']},
            'objects': dict(sorted(objects.items())), 'xyPlane': plane,
            'varset': 'SchemaxisParameters' if parameters else None, 'parameters': parameters,
            'volume': native['volume'], 'area': native['area'], 'bounds': list(native['bounds']),
            'profile': profile_kind,**sheet,**bridge,**({'generation':2} if generation==2 else {})}


def _native_type(kind):
    from .adaptor import DECLARATIONS
    return DECLARATIONS[kind]['native']


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _vector(value, size):
    return isinstance(value, list) and len(value) == size and all(_finite(v) for v in value)


# --------------------------------------------------------------------- mounts

def _binding(raw, parameters, location):
    from .parameters import numeric, evaluate
    keys(raw, ('terms', 'offset'), location)
    terms = raw.get('terms')
    if not isinstance(terms, dict) or not 1 <= len(terms) <= 4:
        fail('INVALID_BINDING', 'Use 1 to 4 parameter terms', location+'.terms')
    canonical = {}
    for identity, coefficient in sorted(terms.items()):
        if identity not in parameters:
            fail('INVALID_BINDING', "Mount bindings may use only this part's own published parameters", location+'.terms.'+str(identity))
        numeric(coefficient, location+'.terms.'+identity)
        if coefficient == 0 or abs(coefficient) > 1000000:
            fail('INVALID_BINDING', 'Coefficients must be nonzero and at most 1000000 in magnitude', location)
        canonical[identity] = coefficient
    offset = numeric(raw.get('offset', 0), location+'.offset')
    if abs(offset) > 1000000:
        fail('INVALID_BINDING', 'Offset magnitude must not exceed 1000000 mm', location)
    binding = {'terms': canonical, 'offset': offset}
    extrema = []
    for low in (True, False):
        values = {k: parameters[k]['minimum' if (c > 0) == low else 'maximum'] for k, c in canonical.items()}
        extrema.append(evaluate(binding, values, location))
    if not -COORDINATE <= extrema[0] <= extrema[1] <= COORDINATE:
        fail('INVALID_BINDING', 'Every mount coordinate across the parameter bounds must stay within 100000 mm', location)
    scale = max(1.0, *(abs(v) for v in extrema))
    for identity, coefficient in canonical.items():
        span = parameters[identity]['maximum'] - parameters[identity]['minimum']
        if abs(coefficient*span) <= max(1e-6, 1e-7*scale)*8:
            fail('UNOBSERVABLE_BINDING', 'Mount response across the parameter bounds is too small to verify', location, parameter=identity)
    binding['value'] = evaluate(binding, {k: v['value'] for k, v in parameters.items()}, location)
    return binding


def _axes(raw, location):
    z = raw.get('z', '+Z')
    # Check the JSON type first: arrays and objects are unhashable and must not reach the table lookup.
    if not isinstance(z, str) or z not in AXES:
        fail('INVALID_MOUNT', 'z must be one of '+', '.join(AXES), location+'.z')
    if 'x' not in raw and z not in ('+Z', '-Z'):
        fail('INVALID_MOUNT', 'Name x explicitly when z is not +Z or -Z', location+'.x')
    x = raw.get('x', '+X')
    if not isinstance(x, str) or x not in AXES:
        fail('INVALID_MOUNT', 'x must be one of '+', '.join(AXES), location+'.x')
    if sum(a*b for a, b in zip(AXES[x], AXES[z])) != 0:
        fail('INVALID_MOUNT', 'x must be perpendicular to z', location)
    zx, x3 = AXES[z], AXES[x]
    y = (zx[1]*x3[2]-zx[2]*x3[1], zx[2]*x3[0]-zx[0]*x3[2], zx[0]*x3[1]-zx[1]*x3[0])
    # Columns are the mount axes in part coordinates (right-handed: y = z x x).
    return z, x, [[x3[i], y[i], zx[i]] for i in range(3)]


def prepare_mounts(raw, facts, location):
    if not isinstance(raw, dict) or not 1 <= len(raw) <= MAX_MOUNTS:
        fail('INVALID_MOUNT', 'Declare 1 to %d named mounts on each sourced part' % MAX_MOUNTS, location)
    result = []
    for identity in sorted(raw):
        where = location+'.'+str(identity)
        mount = name(identity, where)
        if mount in facts['labels'].values():
            fail('INVALID_MOUNT', 'Mount IDs must differ from the part\'s own feature names (native labels)', where)
        item = raw[identity]
        if not isinstance(item, dict):
            fail('INVALID_MOUNT', 'Each mount is an object', where)
        keys(item, ('position', 'z', 'x'), where)
        position = item.get('position', [0, 0, 0])
        if not isinstance(position, list) or len(position) != 3:
            fail('INVALID_MOUNT', 'position has three entries: numbers in mm or parameter bindings', where+'.position')
        coordinates = []
        for axis, value in zip('xyz', position):
            here = where+'.position.'+axis
            if isinstance(value, dict):
                if not facts['parameters']:
                    fail('INVALID_BINDING', 'This part publishes no parameters; use literal mount coordinates', here)
                coordinates.append(_binding(value, facts['parameters'], here))
            else:
                from .parameters import numeric
                numeric(value, here)
                if type(value) is bool or abs(value) > COORDINATE:
                    fail('INVALID_MOUNT', 'Literal mount coordinates are finite mm within 100000', here)
                coordinates.append({'literal': float(value)})
        z, x, rotation = _axes(item, where)
        result.append({'id': mount, 'position': coordinates, 'z': z, 'x': x, 'rotation': rotation,
                       'value': [c['value'] if 'terms' in c else c['literal'] for c in coordinates]})
    return result


# ------------------------------------------------------------- rigid transforms

def frame(position=(0, 0, 0), rotation=((1, 0, 0), (0, 1, 0), (0, 0, 1))):
    return [list(rotation[0])+[position[0]], list(rotation[1])+[position[1]],
            list(rotation[2])+[position[2]], [0, 0, 0, 1]]


def rot_z(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    # Exact quarter turns keep exact signed-axis rotations exact.
    if degrees % 90 == 0:
        c, s = round(c), round(s)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def mul(a, b):
    return [[math.fsum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def inverse(m):
    r = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [-math.fsum(r[i][k]*m[k][3] for k in range(3)) for i in range(3)]
    return [r[0]+[t[0]], r[1]+[t[1]], r[2]+[t[2]], [0, 0, 0, 1]]


def apply(m, p):
    return [math.fsum([*(m[i][k]*p[k] for k in range(3)), m[i][3]]) for i in range(3)]


def flat(m):
    return [float(v) for row in m for v in row]


def square(values):
    return [list(values[0:4]), list(values[4:8]), list(values[8:12]), list(values[12:16])]


def signed_permutation(m, tolerance=1e-12):
    return all(min(abs(m[i][j]), abs(abs(m[i][j])-1)) <= tolerance for i in range(3) for j in range(3))


def mount_frame(mount):
    return frame(mount['value'], mount['rotation'])


def analytic(prepared):
    """Closed-form world poses and placement-independent producer geometry."""
    parts = {p['id']: p for p in prepared['parts']}
    components = {c['id']: c for c in prepared['components']}
    mounts = {p['id']: {m['id']: mount_frame(m) for m in p['mounts']} for p in prepared['parts']}
    root = components[prepared['grounded']]
    world = {root['id']: frame(root['position'], rot_z(root['rotation']))}
    for joint in prepared['joints']:
        parent, child = joint['parent'], joint['child']
        offset = frame(joint['offset'], rot_z(joint['clocking']))
        world[child['component']] = mul(mul(mul(world[parent['component']],
            mounts[components[parent['component']]['part']][parent['mount']]), offset),
            inverse(mounts[components[child['component']]['part']][child['mount']]))
    expected = {'mounts': {pid: {mid: flat(m) for mid, m in items.items()} for pid, items in mounts.items()}, 'components': {}}
    for identity, pose in world.items():
        facts = parts[components[identity]['part']]['source']
        low, high = facts['bounds'][0::2], facts['bounds'][1::2]
        corners = [apply(pose, [x, y, z]) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
        box = [f(c[i] for c in corners) for i in range(3) for f in (min, max)]
        # A signed axis permutation maps the local AABB exactly onto the world AABB.
        # Otherwise pocketed corners may lie inside the rotated box: containment only.
        expected['components'][identity] = {
            'matrix': flat(pose), 'position': [pose[i][3] for i in range(3)],
            'xAxis': [pose[i][0] for i in range(3)], 'zAxis': [pose[i][2] for i in range(3)],
            'volume': facts['volume'], 'area': facts['area'], 'boundsMode': 'exact' if signed_permutation(pose) else 'containment',
            'bounds': box}
    return expected


# ----------------------------------------------------------------------- plan

def plan(document,*,source_facts=None):
    """Sourced-part plan; constructor documents never reach this function."""
    from .assembly import MAX_COMPONENTS, VECTOR, ANGLE, _array
    parts, part_ids, files = [], set(), {}
    for index, item in enumerate(_array(document.get('parts'), 1, MAX_COMPONENTS, '$.parts')):
        if not isinstance(item, dict) or 'source' not in item or 'type' in item or 'options' in item:
            fail('UNSUPPORTED_PART', 'Mixed constructor and sourced parts are not supported; give every part a source and mounts',
                 '$.parts.'+str(index))
        keys(item, ('id', 'source', 'mounts'), '$.parts')
        identity = name(item.get('id'), '$.parts.id')
        if identity in part_ids:
            fail('DUPLICATE_PART', 'Part ID is duplicated', identity)
        facts=(source_facts or {}).get(identity)
        if facts is None:facts=admit(item['source'], identity+'.source')
        parts.append({'id': identity, 'source': facts, 'mounts': prepare_mounts(item.get('mounts'), facts, identity+'.mounts')})
        part_ids.add(identity)
    if sum(p['source']['bytes'] for p in parts) > TOTAL_SOURCE_BYTES or \
            sum(p['source']['expandedBytes'] for p in parts) > TOTAL_EXPANDED_BYTES:
        fail('ASSEMBLY_LIMIT', 'Sources exceed the whole-run budget (128 MiB stored, 512 MiB expanded)', '$.parts')
    lookup = {p['id']: p for p in parts}
    components, component_ids, used = [], set(), set()
    for item in _array(document.get('components'), 2, MAX_COMPONENTS, '$.components'):
        keys(item, ('id', 'part', 'position', 'rotation'), '$.components')
        identity = name(item.get('id'), '$.components.id')
        if identity in component_ids or RESERVED_LABEL.fullmatch(identity):
            fail('DUPLICATE_COMPONENT', 'Component ID is duplicated or reserved by a FreeCAD helper label', identity)
        part = item.get('part')
        if not isinstance(part, str) or part not in part_ids:
            fail('UNKNOWN_PART', 'Component must reference a declared part', identity)
        values = validate_arguments({'position': VECTOR, 'rotation': ANGLE},
                                    {k: item[k] for k in ('position', 'rotation') if k in item})
        components.append({'id': identity, 'part': part, **values})
        used.add(part)
        component_ids.add(identity)
    if used != part_ids:
        fail('UNUSED_PART', 'Every part definition must have a component instance')
    grounded = document.get('grounded')
    if not isinstance(grounded, str) or grounded not in component_ids:
        fail('INVALID_GROUND', 'grounded must name exactly one component')
    part_of = {c['id']: c['part'] for c in components}
    joints, joint_ids, children = [], set(), set()
    for item in _array(document.get('joints'), 1, MAX_COMPONENTS-1, '$.joints'):
        keys(item, ('id', 'type', 'parent', 'child', 'offset', 'clocking'), '$.joints')
        identity = name(item.get('id'), '$.joints.id')
        if identity in joint_ids or identity in component_ids or RESERVED_LABEL.fullmatch(identity):
            fail('DUPLICATE_JOINT', 'Joint IDs must be unique, distinct from component IDs and not a FreeCAD helper label', identity)
        if item.get('type') != 'fixed':
            fail('UNSUPPORTED_JOINT', 'Only fixed joints are qualified; no revolute motion contract', identity)
        ends = {}
        for end in ('parent', 'child'):
            endpoint = item.get(end)
            if isinstance(endpoint, dict) and 'face' in endpoint:
                fail('UNSUPPORTED_FACE', 'Sourced parts join at named mounts, not primitive faces', identity+'.'+end)
            keys(endpoint, ('component', 'mount'), identity+'.'+end)
            component, mount = endpoint.get('component'), endpoint.get('mount')
            if not isinstance(component, str) or component not in component_ids:
                fail('UNKNOWN_COMPONENT', 'Joint references an undeclared component', identity+'.'+end)
            if not isinstance(mount, str) or mount not in {m['id'] for m in lookup[part_of[component]]['mounts']}:
                fail('UNKNOWN_MOUNT', 'Joint mount is not declared on that component\'s part', identity+'.'+end, mount=mount)
            ends[end] = {'component': component, 'mount': mount}
        child, parent = ends['child']['component'], ends['parent']['component']
        if child == parent or child == grounded or child in children:
            fail('INVALID_JOINT_TREE', 'Each non-ground component must have exactly one parent', identity)
        values = validate_arguments({'offset': OFFSET, 'clocking': CLOCKING},
                                    {k: item[k] for k in ('offset', 'clocking') if k in item})
        joints.append({'id': identity, 'type': 'fixed', **ends, 'offset': values['offset'], 'clocking': values['clocking']})
        children.add(child)
        joint_ids.add(identity)
    if children != component_ids-{grounded}:
        fail('INVALID_JOINT_TREE', 'Fixed joints must connect every component to the ground')
    ordered, seen, pending = [], {grounded}, list(joints)
    while pending:
        available = [j for j in pending if j['parent']['component'] in seen]
        if not available:
            fail('INVALID_JOINT_TREE', 'The joint tree contains a disconnected cycle')
        for joint in available:
            ordered.append(joint)
            seen.add(joint['child']['component'])
            pending.remove(joint)
    prepared = {'version': PLAN_VERSION, 'units': 'mm', 'sourced': True, 'parts': parts, 'components': components,
                'grounded': grounded, 'joints': ordered, 'expectedDegreesOfFreedom': 0, 'expectedPublications': 1}
    prepared['native'] = native_names(prepared)
    prepared['expected'] = analytic(prepared)
    return prepared


def native_names(prepared):
    """Deterministic names the adaptor itself creates; source names are recorded natively."""
    mounts = {p['id']+'.'+m['id']: 'Mount%d_%d' % (i, j)
              for i, p in enumerate(prepared['parts']) for j, m in enumerate(p['mounts'])}
    return {'mounts': mounts,
            'components': {c['id']: 'Component%d' % i for i, c in enumerate(prepared['components'])},
            'joints': {j['id']: 'Joint%d' % i for i, j in enumerate(prepared['joints'])},
            'retained': {p['id']: 'sources/source%d.FCStd' % i for i, p in enumerate(prepared['parts'])}}


def labels(prepared, renames):
    """Native labels the adaptor sets; FreeCAD origin helper labels stay as copied."""
    result = {}
    for part in prepared['parts']:
        facts, mapped = part['source'], renames[part['id']]
        result[mapped[facts['body']]] = part['id']+' source'
        if facts['varset']:
            result[mapped[facts['varset']]] = part['id']+' parameters'
        for producer, label in facts['labels'].items():
            if producer != facts['body']:
                result[mapped[producer]] = part['id']+'.'+label
        for mount in part['mounts']:
            result[prepared['native']['mounts'][part['id']+'.'+mount['id']]] = part['id']+'.'+mount['id']
    result.update({prepared['native']['components'][c['id']]: c['id'] for c in prepared['components']})
    result.update({prepared['native']['joints'][j['id']]: j['id'] for j in prepared['joints']})
    return result


def mount_expressions(part, mount, varset):
    from .parameters import expression
    return {'.AttachmentOffset.Base.'+axis: expression(c, varset)
            for axis, c in zip('xyz', mount['position']) if 'terms' in c}


def visibility(prepared, objects, renames):
    visible = {'Assembly', 'Ground', *prepared['native']['components'].values()}
    visible.update(renames[p['id']][p['source']['tip']] for p in prepared['parts'])
    return {name: name in visible for name in objects}


def proxies(prepared):
    return {'Ground': 'ViewProviderGroundedJoint', **{n: 'ViewProviderJoint' for n in prepared['native']['joints'].values()}}


def reusable_inputs(prepared):
    return {p['source']['file']: digest(p['source']['file']) for p in prepared['parts']}


# ------------------------------------------------------------------------ run

def run(document, prepared, directory, *, executable, timeout, gui_executable=None):
    from schemaxis.artifacts import atomic_json, runtime_archive
    from schemaxis.core.runners import Interpreter
    from schemaxis.dispatch import cancellation_requested
    from .process import SubprocessRunner
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        fail('INVALID_EXECUTION', 'Assembly timeout must be finite and positive')
    executable = executable or os.environ.get('FREECAD_CMD')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'Provide an absolute executable FreeCAD command-line launcher')
    deadline = time.monotonic()+timeout
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'Choose a fresh assembly output directory', str(directory))
    for part in prepared['parts']:
        producer = Path(part['source']['run']).resolve()
        if directory == producer or producer in directory.parents or directory in producer.parents:
            fail('UNSUPPORTED_SOURCE', 'Assembly output and source part runs must not contain each other', part['id'])
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    try:
        capture(prepared, directory)
        snapshot = runtime_archive()
        (directory/'runtime.zip').write_bytes(snapshot)
        # The exact retained bytes that native stages open, checked immediately before launch.
        guard_retained(prepared, directory, 'UNSUPPORTED_SOURCE')
        from .source_bridge import verify_before_open
        from schemaxis.dispatch import execution_deadline
        with execution_deadline(max(.001,deadline-time.monotonic())):
            for part in prepared['parts']:
                verify_before_open(directory/prepared['native']['retained'][part['id']],part['source'],executable=executable)
        runner = SubprocessRunner(Interpreter('freecad', str(Path(executable).resolve())), directory, timeout=timeout)
        for stage in ('capture', 'build', 'reopen'):
            runner.timeout = deadline-time.monotonic()
            if runner.timeout <= 0:
                fail('RUNNER_TIMED_OUT', 'Assembly execution exhausted its total timeout')
            source = ('import sys\nsys.path.insert(0,'+repr(str(directory/'runtime.zip'))+')\n'
                      'from schemaxis.adaptors.freecad.assembly_sources_native import '+stage+'\n'
                      'from schemaxis.native_boundary import execute_guarded\n'
                      'execute_guarded('+stage+','+repr(str(directory))+')\n')
            report = runner(source)
            atomic_json(directory/(stage+'-submission.json'), report.to_dict())
            if (directory/'native-fault.json').exists():
                raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
            if cancellation_requested():
                fail('RUNNER_CANCELLED', 'Assembly execution cancelled')
            if stage == 'capture':
                # Stored history must be what recompute reproduces before anything is built from it.
                check_captured(prepared, directory)
        result = verify(directory, require_result=False,executable=executable,
                        verification_timeout=max(.001,deadline-time.monotonic()))
        if gui_executable:
            # Complete admission above precedes EVERY GUI document restore.
            # Inspect without saving: minimal visibility and proxy intent stay
            # byte-identical to the verified native publication.
            if cancellation_requested():fail('RUNNER_CANCELLED','Assembly GUI inspection cancelled before launch')
            if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','Assembly budget expired before GUI inspection')
            from .assembly_sources_gui import inspect_verified
            result['guiInspection']=inspect_verified(directory,prepared,gui_executable,max(.001,deadline-time.monotonic()),
                                                     verified_sha256=result['nativeSha256'])
        # The whole-run budget and cancellation also cover the final host verification.
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'Assembly execution cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'Assembly execution exhausted its total timeout during verification')
        result.update(status='succeeded', runtimeSha256=hashlib.sha256(snapshot).hexdigest())
        atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        if (directory/'native-fault.json').exists():
            error = SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False,
            'fault': error.fault.to_dict() if isinstance(error, SchemaxisError) else {'message': str(error)}})
        raise error


def envelope_facts(facts):
    from .source_bridge import capability
    key=capability(facts)
    return {'objects': facts['objects'], 'parameters': facts['parameters'],'generation':facts.get('generation',1),
            **({'spreadsheet':facts['spreadsheet']} if 'spreadsheet' in facts else {}),
            **({key:facts[key],'sourceFrame':facts.get('sourceFrame')} if key else {})}


def guard_retained(prepared, directory, code):
    """Digest and closed envelope of each retained copy, without any native open."""
    from . import source_envelope
    for part in prepared['parts']:
        retained = directory/prepared['native']['retained'][part['id']]
        if digest(_plain(retained, part['id'], code)) != part['source']['sha256']:
            fail('INPUT_CHANGED', 'Retained source copy changed', part['id'])
        source_envelope.inspect(retained, envelope_facts(part['source']), part['id']+'.retained', code)


def capture(prepared, directory):
    """Reverify each producer and its closed envelope, then retain a byte-identical private copy."""
    from schemaxis.artifacts import atomic_json
    from .adaptor import verify as verify_part
    from . import source_envelope
    (directory/'sources').mkdir()
    records = {}
    for part in prepared['parts']:
        facts = part['source']
        verify_part(facts['run'])
        source = check_archive(facts['file'], part['id']+'.source')
        retained = directory/prepared['native']['retained'][part['id']]
        before = digest(source)
        if before != facts['sha256']:
            fail('INPUT_CHANGED', 'Source part changed after planning', part['id'])
        source_envelope.inspect(source, envelope_facts(facts), part['id']+'.source')
        shutil.copyfile(source, retained)
        if digest(retained) != before or digest(source) != before:
            fail('INPUT_CHANGED', 'Source part changed during capture', part['id'])
        records[part['id']] = {'file': facts['file'], 'retained': str(retained), 'sha256': before,
                               'receiptSha256': facts['receiptSha256']}
    atomic_json(directory/'sources.json', records)


# --------------------------------------------------------------------- verify

def close(a, b, rel=1e-7, absolute=1e-6):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, rel, absolute) for x, y in zip(a, b))
    return _finite(a) and _finite(b) and math.isclose(a, b, rel_tol=rel, abs_tol=absolute)


def verify(directory, require_result=True,*,executable=None,verification_timeout=120):
    """Share one verification budget across source admission and copied history.

    A run can supply its remaining budget; a standalone call keeps the existing
    120-second default. Neither case extends a tighter enclosing deadline.
    """
    from schemaxis.dispatch import execution_deadline,remaining_timeout
    with execution_deadline(verification_timeout):
        remaining_timeout(verification_timeout)
        result=_verify(directory,require_result,executable=executable,
                       verification_timeout=verification_timeout)
        remaining_timeout(verification_timeout)
        return result


def _verify(directory, require_result=True,*,executable=None,verification_timeout=120):
    from .assembly import plan as assembly_plan
    from .adaptor import verify as verify_part
    from .assembly_sources_saved import verify_saved
    directory = Path(directory).absolute()

    def require(condition, message, **detail):
        if not condition:
            fail('VERIFICATION_FAILED', message, str(directory), **detail)
    authored = json.loads((directory/'authored.json').read_text())
    stored=json.loads((directory/'plan.json').read_text())
    from .source_bridge import replay_plan
    prepared = replay_plan(directory,authored,stored)
    require(prepared.get('sourced') is True, 'Not a sourced assembly run')
    require(json.loads((directory/'plan.json').read_text()) == prepared, 'Assembly plan differs from authored input')
    if require_result:
        require(json.loads((directory/'result.json').read_text()).get('verified') is True, 'Assembly execution is incomplete')
    sources = json.loads((directory/'sources.json').read_text())
    require(set(sources) == {p['id'] for p in prepared['parts']}, 'Captured source membership differs')
    retained_paths = {}
    for part in prepared['parts']:
        record, facts = sources[part['id']], part['source']
        retained = directory/prepared['native']['retained'][part['id']]
        require(record == {'file': facts['file'], 'retained': str(retained), 'sha256': facts['sha256'],
                           'receiptSha256': facts['receiptSha256']}, 'Captured source provenance differs', part=part['id'])
        check_archive(retained, part['id'], code='VERIFICATION_FAILED')
        from .source_bridge import capability
        if digest(retained) != facts['sha256'] or not capability(facts) and digest(facts['file']) != facts['sha256']:
            fail('INPUT_CHANGED', 'Source part or its retained copy changed', part['id'])
        if not capability(facts):verify_part(facts['run'])
        retained_paths[part['id']] = retained
    guard_retained(prepared, directory, 'VERIFICATION_FAILED')
    from .source_bridge import verify_before_open
    for part in prepared['parts']:
        verify_before_open(retained_paths[part['id']],part['source'],executable=executable)
    captured = json.loads((directory/'capture.json').read_text())
    built = json.loads((directory/'built.json').read_text())
    reopened = json.loads((directory/'verification.json').read_text())
    pids = [r.get('pid') for r in (captured, built, reopened)]
    require(all(type(p) is int for p in pids) and len(set(pids)) == 3, 'Capture, build and reopening must use separate native processes')
    for receipt, stage in ((captured, 'capture'), (built, 'build'), (reopened, 'reopen')):
        require(receipt.get('stage') == stage and receipt.get('definition') == prepared, 'Native assembly definition differs', stage=stage)
        require(isinstance(receipt.get('runtime'), list) and receipt['runtime'][:2] == ['1', '1'], 'Native runtime differs', stage=stage)
    centres = {}
    for part in prepared['parts']:
        facts, observed = part['source'], captured.get('parts', {}).get(part['id'], {})
        require(observed.get('objects') == facts['objects'] and observed.get('tip') == facts['tip'],
                'Captured source membership differs from its producer', part=part['id'])
        shape = observed.get('shape', {})
        require(shape.get('valid') is True and shape.get('solids') == 1, 'Captured source is not one valid solid', part=part['id'])
        for measure in ('volume', 'area', 'bounds'):
            require(close(shape.get(measure), facts[measure]), 'Captured source differs from its producer receipt', part=part['id'], measure=measure)
        require(_vector(shape.get('centreOfMass'), 3), 'Captured centre of mass is absent', part=part['id'])
        centres[part['id']] = shape['centreOfMass']
        check_history(part, observed, retained_paths[part['id']], require)
    renames = built.get('renames')
    check_renames(prepared, renames, require)
    require(reopened.get('renames') == renames, 'Reopened source names differ from the build')
    for receipt, stages in ((built, ('initial', 'solved')), (reopened, ('persisted', 'solved'))):
        for label in stages:
            check_snapshot(prepared, receipt.get('snapshots', {}).get(label), renames, centres, require, label)
        check_solver(prepared, receipt.get('solver'), require)
    path = directory/'model.FCStd'
    require(path.is_file() and not path.is_symlink() and path.resolve().parent == directory.resolve(), 'Native assembly file is absent or escaped')
    artifact = reopened.get('artifact', {})
    require(reopened.get('artifacts') == [artifact], 'Assembly publication membership differs')
    require(artifact.get('file') == str(path) and artifact.get('kind') == 'cadScene' and artifact.get('units') == 'mm',
            'Assembly artifact metadata differs')
    require(artifact.get('sha256') == digest(path), 'Native assembly file changed')
    from .source_bridge import requires_copy_regeneration
    if any(requires_copy_regeneration(p['source']) for p in prepared['parts']):
        from .history_copy_verify import regenerate
        from schemaxis.dispatch import remaining_timeout
        with regenerate(directory,prepared,retained_paths,executable=executable,
                        timeout=remaining_timeout(verification_timeout)) as regenerated:
            verify_saved(prepared,path,renames,retained_paths,regenerated)
    else:
        verify_saved(prepared, path, renames, retained_paths)
    return {'verified': True, 'artifacts': 1, 'components': len(prepared['components']), 'joints': len(prepared['joints']),
            'sourceParts': len(prepared['parts']), 'expectedDegreesOfFreedom': 0, 'runtime': reopened['runtime'],
            'solver': 'FreeCAD built-in Assembly', 'nativeFile': str(path),'nativeSha256':artifact['sha256']}


def check_captured(prepared, directory):
    captured = json.loads((Path(directory)/'capture.json').read_text())

    def require(condition, message, **detail):
        if not condition:
            fail('VERIFICATION_FAILED', message, str(directory), **detail)
    require(captured.get('stage') == 'capture' and captured.get('definition') == prepared, 'Native capture evidence differs')
    for part in prepared['parts']:
        check_history(part, captured.get('parts', {}).get(part['id'], {}),
                      Path(directory)/prepared['native']['retained'][part['id']], require)


# A recompute after reopening reproduces stored history shapes up to floating-point representation
# noise: parameters round-trip through 16 saved decimals. Native evidence over 79 qualified producers:
# at most about 10 ULP (6.2e-15 mm vertex, 2.2e-15 relative volume). Substitutions differ by feature sizes.
HISTORY_ULPS = 64


def _near(a, b, scale):
    return _finite(a) and _finite(b) and abs(a-b) <= HISTORY_ULPS*math.ulp(max(abs(a), abs(b), scale))


def same_history_shape(a, b):
    """Counts and types exact; every measure, bound, centre, vertex, face and edge within the ULP rule."""
    keys = {'type', 'valid', 'vertices', 'faces', 'edges', 'counts', 'volume', 'area', 'length', 'bounds', 'centreOfMass'}
    if not isinstance(a, dict) or not isinstance(b, dict) or set(a) != keys or set(b) != keys:
        return False
    if a['valid'] is not True or b['valid'] is not True or a['type'] != b['type'] or a['counts'] != b['counts']:
        return False
    if not _vector(a['bounds'], 6) or not _vector(b['bounds'], 6):
        return False
    scale = max(1.0, *(abs(v) for v in a['bounds'] + b['bounds']))
    if not all(_near(a[k], b[k], scale) for k in ('volume', 'area', 'length')):
        return False
    if not all(_near(x, y, scale) for x, y in zip(a['bounds'], b['bounds'])):
        return False
    if (a['centreOfMass'] is None) != (b['centreOfMass'] is None) or (
            a['centreOfMass'] is not None and not all(_near(x, y, scale) for x, y in zip(a['centreOfMass'], b['centreOfMass']))):
        return False
    for kind in ('faces', 'edges'):
        if len(a[kind]) != len(b[kind]) or any(x[0] != y[0] or not _near(x[1], y[1], scale) for x, y in zip(a[kind], b[kind])):
            return False
    if len(a['vertices']) != len(b['vertices']):
        return False
    if all(all(_near(x, y, scale) for x, y in zip(p, q)) for p, q in zip(a['vertices'], b['vertices'])):
        return True
    # Near-equal coordinates may reorder a sorted list: match one to one, within a bounded size.
    if len(a['vertices']) > 2000:
        return False
    remaining = list(b['vertices'])
    for point in a['vertices']:
        match = next((i for i, other in enumerate(remaining)
                      if all(_near(x, y, scale) for x, y in zip(point, other))), None)
        if match is None:
            return False
        remaining.pop(match)
    return True


def check_history(part, observed, retained, require):
    """Each stored history payload the source names must be what its feature history reproduces.

    Not a proof of exact shape identity: counts and types are exact, and every measure, bound, centre
    of mass, vertex coordinate, face (type, area) and edge (type, length) must agree within the
    floating-point representation rule above.
    """
    from .source_envelope import inspect
    payloads = inspect(retained, envelope_facts(part['source']), part['id'], 'VERIFICATION_FAILED')['payloads']
    named = {obj+'.'+prop for obj, prop, tag in payloads.values() if tag == 'Part'}
    record = observed.get('history', {})
    stored, recomputed = record.get('stored'), record.get('recomputed')
    complete = (observed.get('recomputeStates') == {} and isinstance(stored, dict) and isinstance(recomputed, dict)
                and set(stored) == named and set(recomputed) == named)
    require(complete, 'Captured history evidence does not cover exactly the payloads the source names', part=part['id'])
    if not complete:
        return
    for key in sorted(named):
        a, b = stored[key], recomputed[key]
        if a is None or b is None:
            require(a is None and b is None, 'A stored history shape is not reproduced by recompute', part=part['id'], shape=key)
            continue
        require(same_history_shape(a, b), 'A stored history shape differs from what its history reproduces',
                part=part['id'], shape=key)


def check_renames(prepared, renames, require):
    require(isinstance(renames, dict) and set(renames) == {p['id'] for p in prepared['parts']}, 'Source rename map is absent')
    seen = set(FIXED_NAMES) | set(prepared['native']['components'].values()) | set(prepared['native']['joints'].values()) \
        | set(prepared['native']['mounts'].values())
    for part in prepared['parts']:
        mapped = renames[part['id']]
        require(isinstance(mapped, dict) and set(mapped) == set(part['source']['objects']), 'Source rename domain differs', part=part['id'])
        values = list(mapped.values())
        require(all(isinstance(v, str) and v for v in values) and len(set(values)) == len(values) and not seen & set(values),
                'Source rename map is not a bijection onto fresh names', part=part['id'])
        seen.update(values)


def check_snapshot(prepared, snap, renames, centres, require, label):
    require(isinstance(snap, dict), 'Native assembly snapshot is absent', snapshot=label)
    expected = prepared['expected']
    require(snap.get('badStates') == {} and snap.get('externalLinks') == [] and len(snap.get('documents', [])) == 1,
            'Native assembly has invalid objects, other documents or external links', snapshot=label)
    require(snap.get('proxies') == {'Ground': 'GroundedJoint', **{n: 'Joint' for n in prepared['native']['joints'].values()}},
            'Native Python proxies differ from the controlled joint set', snapshot=label)
    part_of = {c['id']: c['part'] for c in prepared['components']}
    for component in prepared['components']:
        identity = component['id']
        observed, wanted = snap.get('components', {}).get(identity, {}), expected['components'][identity]
        source = renames[component['part']][next(p for p in prepared['parts'] if p['id'] == component['part'])['source']['body']]
        require(observed.get('name') == prepared['native']['components'][identity] and observed.get('linked') == source
                and observed.get('linkTransform') is False and observed.get('label') == identity,
                'Component is not a link to its embedded source Body', component=identity, snapshot=label)
        require(close(observed.get('matrix'), wanted['matrix']), 'Component placement differs from the analytic pose',
                component=identity, snapshot=label)
        shape = observed.get('shape', {})
        require(shape.get('valid') is True and shape.get('solids') == 1, 'Component geometry is invalid', component=identity, snapshot=label)
        for measure in ('volume', 'area'):
            require(close(shape.get(measure), wanted[measure]), 'Component '+measure+' differs from its producer', component=identity, snapshot=label)
        centre = apply(square(wanted['matrix']), centres[part_of[identity]])
        require(close(shape.get('centreOfMass'), centre), 'Component centre of mass differs from the transformed captured centre',
                component=identity, snapshot=label)
        require(bounds_agree(wanted, shape.get('bounds')),
                'Component bounds differ from the permuted producer bounds' if wanted['boundsMode'] == 'exact'
                else 'Component bounds escape the rotated producer bounding box', component=identity, snapshot=label)
    for part in prepared['parts']:
        for mount in part['mounts']:
            key = part['id']+'.'+mount['id']
            observed = snap.get('mounts', {}).get(key, {})
            require(observed.get('name') == prepared['native']['mounts'][key] and observed.get('body') == renames[part['id']][part['source']['body']]
                    and observed.get('label') == key and observed.get('mapMode') == 'ObjectXY'
                    and observed.get('support') == [[renames[part['id']][part['source']['xyPlane']], ['']]],
                    'Mount identity, ownership or attachment differs', mount=key, snapshot=label)
            require(close(observed.get('matrix'), expected['mounts'][part['id']][mount['id']]), 'Mount frame differs from its authored value',
                    mount=key, snapshot=label)
            check_mount_expressions(part, mount, renames, observed.get('expressions'), require, key)
    for joint in prepared['joints']:
        observed = snap.get('joints', {}).get(joint['id'], {})
        refs = []
        for end in ('parent', 'child'):
            datum = prepared['native']['mounts'][part_of[joint[end]['component']]+'.'+joint[end]['mount']]
            refs.append([prepared['native']['components'][joint[end]['component']], [datum+'.', datum+'.']])
        offset = flat(frame(joint['offset'], rot_z(joint['clocking'])))
        require(observed.get('name') == prepared['native']['joints'][joint['id']] and observed.get('label') == joint['id']
                and observed.get('jointType') == 'Fixed' and observed.get('suppressed') is False
                and observed.get('detach') == [False, False]
                and [observed.get('reference1'), observed.get('reference2')] == refs,
                'Native fixed joint identity, state or mount references differ', joint=joint['id'], snapshot=label)
        identity = flat(frame())
        require(close(observed.get('offset1'), offset) and close(observed.get('offset2'), identity)
                and close(observed.get('placement1'), offset) and close(observed.get('placement2'), identity),
                'Joint connector offsets differ (authored offset/clocking are parent Offset1; Offset2 is identity)',
                joint=joint['id'], snapshot=label)
        ends = []
        for end, local in (('parent', 'placement1'), ('child', 'placement2')):
            component = snap['components'][joint[end]['component']]
            mount = snap['mounts'][part_of[joint[end]['component']]+'.'+joint[end]['mount']]
            ends.append(mul(mul(square(component['matrix']), square(mount['matrix'])), square(observed[local])))
        residual = mul(inverse(ends[0]), ends[1])
        require(close(flat(residual), identity), 'Joint connector frames do not coincide', joint=joint['id'], snapshot=label)
    ground = snap.get('ground', {})
    require(ground == {'object': prepared['native']['components'][prepared['grounded']]}, 'Grounded joint does not hold the declared root',
            snapshot=label)


def bounds_agree(wanted, bounds):
    """Exact only for signed axis permutations; otherwise a labelled containment check.

    Rotating the producer's local box by an arbitrary angle gives a box that
    contains the part, but pockets may remove the support corners, so equality
    is not implied. Placement, volume and centre of mass carry the exactness.
    """
    if not _vector(bounds, 6) or any(bounds[2*i] > bounds[2*i+1] for i in range(3)):
        return False
    if wanted['boundsMode'] == 'exact':
        return close(bounds, wanted['bounds'])
    tolerance = 1e-6*max(1.0, *(abs(v) for v in wanted['bounds']))
    return all(bounds[2*i] >= wanted['bounds'][2*i]-tolerance and bounds[2*i+1] <= wanted['bounds'][2*i+1]+tolerance
               for i in range(3))


def check_mount_expressions(part, mount, renames, observed, require, key):
    from .parameters import check_expression
    require(isinstance(observed, list) and all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, str) for v in p) for p in observed),
            'Mount expressions are malformed', mount=key)
    actual = dict(observed)
    wanted = {'.AttachmentOffset.Base.'+axis: c for axis, c in zip('xyz', mount['position']) if 'terms' in c}
    require(len(actual) == len(observed) and set(actual) == set(wanted), 'Mount expression membership differs', mount=key)
    varset = renames[part['id']].get(part['source']['varset']) if part['source']['varset'] else None
    for path, binding in wanted.items():
        check_expression(actual[path], binding, key+path, varset)


def check_solver(prepared, solver, require):
    require(isinstance(solver, dict) and type(solver.get('returnCode')) is int and solver['returnCode'] == 0, 'Native assembly solver failed')
    moving = [c['id'] for c in prepared['components'] if c['id'] != prepared['grounded']]
    require(solver.get('displaced') == moving, 'Solver perturbation membership differs')
    for phase in ('before', 'perturbed', 'after'):
        require(isinstance(solver.get(phase), dict) and set(solver[phase]) == {c['id'] for c in prepared['components']},
                'Solver pose evidence is incomplete')
    for identity, wanted in prepared['expected']['components'].items():
        require(close(solver['before'][identity], wanted['matrix']) and close(solver['after'][identity], wanted['matrix']),
                'Solver did not restore the analytic pose', component=identity)
        moved = not close(solver['perturbed'][identity], wanted['matrix'])
        require(moved == (identity in moving), 'Solver perturbation was not applied exactly to ungrounded components', component=identity)
