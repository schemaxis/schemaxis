"""Deterministically author the original synthetic IFC4 ASCII STEP fixtures for the IfcOpenShell wall schedule.

The files are written as plain text by this script; no IfcOpenShell, no real building data and no external model is used.
Usage: python3 tools/author_ifcopenshell_fixtures.py [--check] [DIRECTORY]
"""
import hashlib
from pathlib import Path
import sys

DEFAULT = Path(__file__).resolve().parents[1] / 'examples/schemaxis/fixtures/ifcopenshell'
HEADER = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
          "FILE_NAME('synthetic.ifc','2026-10-26T00:00:00',(''),(''),'schemaxis fixture author','schemaxis fixture author','');\n"
          "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n")
FOOTER = 'ENDSEC;\nEND-ISO-10303-21;\n'


def guid(n): return '0SYN%018d' % n
def text(value): return 'IFCLABEL(' + quote(value) + ')'
def quote(value): return "'" + value.replace("'", "''") + "'"


class Model:
    def __init__(self): self.lines, self.count = [], 0

    def add(self, name, *args):
        self.count += 1
        self.lines.append(f'#{self.count}={name}({",".join(args)});')
        return '#%d' % self.count

    def render(self): return HEADER + '\n'.join(self.lines) + '\n' + FOOTER


def unit(model, kind, prefix, name): return model.add('IFCSIUNIT', '*', f'.{kind}.', f'.{prefix}.' if prefix else '$', f'.{name}.')


def build(units, walls, type_props, quantity_kind='IFCQUANTITYLENGTH', extra=()):
    """units: list of (kind, prefix, name). walls: dicts with name, type (bool), pset (dict of name->typed text), qto (dict name->(kind, lexeme))."""
    m = Model()
    refs = [unit(m, *u) for u in units]
    assignment = m.add('IFCUNITASSIGNMENT', '(' + ','.join(refs) + ')')
    m.add('IFCPROJECT', quote(guid(1)), '$', quote('Synthetic wall schedule'), '$', '$', '$', '$', '$', assignment)
    props = [m.add('IFCPROPERTYSINGLEVALUE', quote(k), '$', v, '$') for k, v in type_props.items()]
    wall_type = m.add('IFCWALLTYPE', quote(guid(2)), '$', quote('WT-01'), '$', '$', '(' + m.add('IFCPROPERTYSET', quote(guid(3)), '$', quote('Pset_WallCommon'), '$', '(' + ','.join(props) + ')') + ')', '$', '$', '$', '.STANDARD.')
    serial, typed = 10, []
    for wall in walls:
        serial += 1
        ref = m.add('IFCWALL', quote(guid(serial)), '$', quote(wall['name']) if wall['name'] else '$', '$', '$', '$', '$', '$', '.STANDARD.')
        if wall.get('type'): typed.append(ref)
        if wall.get('pset'):
            members = [m.add('IFCPROPERTYSINGLEVALUE', quote(k), '$', v, '$') for k, v in wall['pset'].items()]
            serial += 1
            pset = m.add('IFCPROPERTYSET', quote(guid(serial)), '$', quote('Pset_WallCommon'), '$', '(' + ','.join(members) + ')')
            serial += 1
            m.add('IFCRELDEFINESBYPROPERTIES', quote(guid(serial)), '$', '$', '$', f'({ref})', pset)
        if wall.get('notes'):
            members = [m.add('IFCPROPERTYSINGLEVALUE', quote(k), '$', v, '$') for k, v in wall['notes'].items()]
            serial += 1
            pset = m.add('IFCPROPERTYSET', quote(guid(serial)), '$', quote('Pset_ScheduleNotes'), '$', '(' + ','.join(members) + ')')
            serial += 1
            m.add('IFCRELDEFINESBYPROPERTIES', quote(guid(serial)), '$', '$', '$', f'({ref})', pset)
        if wall.get('qto'):
            members = [m.add(kind, quote(k), '$', '$', lexeme, '$') for k, (kind, lexeme) in wall['qto'].items()]
            serial += 1
            qto = m.add('IFCELEMENTQUANTITY', quote(guid(serial)), '$', quote('Qto_WallBaseQuantities'), '$', '$', '(' + ','.join(members) + ')')
            serial += 1
            m.add('IFCRELDEFINESBYPROPERTIES', quote(guid(serial)), '$', '$', '$', f'({ref})', qto)
    m.add('IFCRELDEFINESBYTYPE', quote(guid(9)), '$', '$', '$', '(' + ','.join(typed) + ')', wall_type)
    for line in extra: m.lines.append(line)
    return m.render()


L = 'IFCQUANTITYLENGTH'
BASELINE = dict(units=[('LENGTHUNIT', 'MILLI', 'METRE')], type_props={'FireRating': text('2HR'), 'IsExternal': 'IFCBOOLEAN(.T.)'}, walls=[
    {'name': 'North wall', 'type': True, 'qto': {'Length': (L, '2500.'), 'Height': (L, '3000.')}},
    {'name': 'Core wall', 'type': True, 'pset': {'FireRating': text('1HR')}, 'notes': {'Note': text('+reviewed =later')}, 'qto': {'Length': (L, '4000.')}},
    {'name': None, 'type': False, 'pset': {'FireRating': text('0123')}, 'notes': {'Note': text('007')}, 'qto': {'Length': (L, '1800.'), 'Height': (L, '2700.')}}])
VARIANT = dict(BASELINE, walls=[dict(BASELINE['walls'][0], qto={'Length': (L, '2600.'), 'Height': (L, '3000.')}), *BASELINE['walls'][1:]])
AREAS = dict(units=[('LENGTHUNIT', 'MILLI', 'METRE'), ('AREAUNIT', 'MILLI', 'SQUARE_METRE'), ('VOLUMEUNIT', 'MILLI', 'CUBIC_METRE')], type_props={'IsExternal': 'IFCBOOLEAN(.F.)', 'Count': 'IFCINTEGER(0)'}, walls=[
    {'name': 'Metric A', 'type': True, 'qto': {'Length': (L, '2500.'), 'NetSideArea': ('IFCQUANTITYAREA', '7500000.'), 'NetVolume': ('IFCQUANTITYVOLUME', '1500000000.')}},
    {'name': 'Metric B', 'type': True, 'qto': {'Length': (L, '0.'), 'NetSideArea': ('IFCQUANTITYAREA', '1.5E6'), 'NetVolume': ('IFCQUANTITYVOLUME', '2.5E8')}}])
METRE = dict(BASELINE, units=[('LENGTHUNIT', None, 'METRE')], walls=[{'name': 'Metre A', 'type': True, 'qto': {'Length': (L, '2.5'), 'Height': (L, '3.')}},
                                                                    {'name': 'Metre B', 'type': True, 'qto': {'Length': (L, '4.'), 'Height': (L, '2.4')}}])
FIXTURES = {'walls-baseline.ifc': BASELINE, 'walls-variant.ifc': VARIANT, 'walls-areas.ifc': AREAS, 'walls-metre.ifc': METRE}


def main(argv):
    check = '--check' in argv
    paths = [a for a in argv if not a.startswith('--')]
    target = Path(paths[0]) if paths else DEFAULT
    target.mkdir(parents=True, exist_ok=True)
    status = 0
    for name, spec in FIXTURES.items():
        content = build(**spec).encode('ascii')
        path = target / name
        if check:
            if not path.is_file() or path.read_bytes() != content: print('differs', name); status = 1
        else: path.write_bytes(content)
        print(name, hashlib.sha256(content).hexdigest(), len(content))
    return status


if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
