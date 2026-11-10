"""Native IfcOpenShell worker, run inside the private IfcOpenShell interpreter. It never sees host expectations.

Usage: worker.py --identity | worker.py SOURCE.ifc INTENT.json OUTPUT.json
It opens the captured file, selects plain IfcWall occurrences and looks up every requested property or quantity set
with explicit non-inheriting lookups (the library's inherited lookup can return a whole type set), recording which
object each value came from. Scales come from the library's own unit conversion and are compared by the host. The identity hashes the wrapper and the util.element and
util.unit modules that implement the lookups and scales, before and after the extraction.
"""
import hashlib
import json
import math
import sys


def identity():
    import ifcopenshell
    from pathlib import Path
    wrapper = sorted(Path(ifcopenshell.__file__).parent.glob('_ifcopenshell_wrapper*.so'))
    data = wrapper[0].read_bytes() if wrapper else b''
    modules = {name: hashlib.sha256((Path(ifcopenshell.__file__).parent / name).read_bytes()).hexdigest() for name in ('util/element.py', 'util/unit.py')}
    return {'ifcopenshell': ifcopenshell.version, 'python': '.'.join(map(str, sys.version_info[:3])), 'wrapper': wrapper[0].name if wrapper else None,
            'wrapperBytes': len(data), 'wrapperSha256': hashlib.sha256(data).hexdigest(), 'modules': modules}


def lookup(util, owner, column, scope):
    if owner is None: return False, None
    if column['source'] == 'property': found = util.get_pset(owner, column['set'], psets_only=True, should_inherit=False)
    else: found = util.get_pset(owner, column['set'], qtos_only=True, should_inherit=False)
    key = column['property'] if column['source'] == 'property' else column['quantityName']
    if not isinstance(found, dict) or key not in found: return False, None
    return True, found[key]


def extract(source, intent, out):
    import ifcopenshell
    import ifcopenshell.util.element as util
    import ifcopenshell.util.unit as unit
    before = identity()
    model = ifcopenshell.open(source)
    needed = sorted({{'length': 'LENGTHUNIT', 'area': 'AREAUNIT', 'volume': 'VOLUMEUNIT'}[c['quantity']] for c in intent['columns'] if c['source'] == 'quantity'})
    scales = {name: unit.calculate_unit_scale(model, name) for name in needed}
    walls = sorted(model.by_type(intent['class'], include_subtypes=False), key=lambda w: w.GlobalId)
    rows = []
    for wall in walls:
        wall_type = util.get_type(wall)
        cells = []
        for column in intent['columns']:
            here, raw = lookup(util, wall, column, 'occurrence')
            origin = 'occurrence' if here else 'missing'
            if not here and column['source'] == 'property' and intent['inheritance'] == 'occurrence-overrides-type':
                there, raw = lookup(util, wall_type, column, 'type')
                if there: origin = 'type'
            if origin == 'missing': raw = None
            converted = raw
            if column['source'] == 'quantity' and raw is not None:
                converted = raw * scales[{'length': 'LENGTHUNIT', 'area': 'AREAUNIT', 'volume': 'VOLUMEUNIT'}[column['quantity']]]
            if isinstance(converted, float) and not math.isfinite(converted): raise ValueError('non-finite native value')
            cells.append({'origin': origin, 'raw': raw, 'value': converted})
        rows.append({'guid': wall.GlobalId, 'name': wall.Name, 'typeGuid': wall_type.GlobalId if wall_type is not None else None, 'cells': cells})
    after = identity()
    if after != before: raise ValueError('the native library or its lookup modules changed while the extraction ran')
    result = {'version': 'schemaxis.ifcopenshell.native/1', 'identity': after, 'schema': model.schema, 'scales': scales, 'rows': rows}
    with open(out, 'x') as stream: stream.write(json.dumps(result, sort_keys=True, allow_nan=False, indent=1) + '\n')


if __name__ == '__main__':
    if sys.argv[1:] == ['--identity']: print(json.dumps(identity(), sort_keys=True))
    elif len(sys.argv) == 4: extract(sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3])
    else: raise SystemExit('usage: worker.py --identity | SOURCE INTENT OUTPUT')
