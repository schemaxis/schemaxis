"""Host-only IfcOpenShell wall schedule checks: planning, the independent STEP reader, exact refusals and native-table comparison.

No native process runs. The expected values are literals worked out by hand from the synthetic fixtures.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from schemaxis.adaptors import registry
from schemaxis.adaptors.calc import typed_table
from schemaxis.adaptors.ifcopenshell import adaptor, step
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples/schemaxis'
FIXTURES = EXAMPLES / 'fixtures/ifcopenshell'


def example(name): return json.loads((EXAMPLES / name).read_text())
def fixture(name): return (FIXTURES / name).read_text()


def schedule(text, document=None):
    p = adaptor.plan(document or example('ifcopenshell-baseline.json'))
    return step.resolve(step.parse(text.encode('utf-8') if isinstance(text, str) else text), p), p


class IfcOpenShell(unittest.TestCase):
    def fault(self, action, code, location=None):
        with self.assertRaises(SchemaxisError) as raised: action()
        self.assertEqual(raised.exception.fault.code, code, raised.exception.fault.to_dict())
        if location: self.assertIn(location, raised.exception.fault.location or '')
        return raised.exception.fault

    def mutate(self, old, new, code, location=None, name='walls-baseline.ifc', document=None, count=1):
        text = fixture(name)
        self.assertEqual(text.count(old), count, old)
        return self.fault(lambda: schedule(text.replace(old, new), document), code, location)

    def test_registered_without_framework_branches(self):
        self.assertIn('ifcopenshell', [p['id'] for p in registry.discover()['providers']])
        for path in (ROOT / 'src/schemaxis').glob('*.py'): self.assertNotIn('ifcopenshell', path.read_text().lower(), path.name)
        manifest = json.loads((ROOT / 'src/schemaxis/adaptors/ifcopenshell/adaptor.json').read_text())
        self.assertEqual(manifest['routes']['schemaxis.ifcopenshell/1']['acceptedArtifacts'], [])

    def test_plan_is_deterministic_immutable_and_closed(self):
        document = example('ifcopenshell-baseline.json');original = copy.deepcopy(document)
        first = adaptor.plan(document)
        self.assertEqual(first, adaptor.plan(document));self.assertEqual(document, original)
        self.assertEqual((first['class'], first['missing'], first['inheritance'], first['zeroQuantity']), ('IfcWall', 'null', 'occurrence-overrides-type', 'accept'))
        self.assertNotEqual(first, adaptor.plan(example('ifcopenshell-variant.json')))
        self.assertEqual(adaptor.intent_of(first), {'class': 'IfcWall', 'columns': first['columns'], 'inheritance': 'occurrence-overrides-type'})
        self.assertNotIn('missing', adaptor.intent_of(first))

    def test_planning_faults(self):
        self.fault(lambda: adaptor.plan(example('ifcopenshell-duplicate-column-invalid.json')), 'INVALID_COLUMN', '$.columns[1]')
        self.fault(lambda: adaptor.plan(example('ifcopenshell-source-relative-invalid.json')), 'INVALID_SOURCE', '$.source.path')
        self.fault(lambda: adaptor.plan(example('ifcopenshell-class-invalid.json')), 'INVALID_ARGUMENT', '$.arguments.class')
        self.fault(lambda: adaptor.plan(example('ifcopenshell-missing-invalid.json')), 'INVALID_ARGUMENT', '$.arguments.missing')
        for change, location in ((lambda d: d['columns'][0].pop('valueType'), '$.columns[0]'), (lambda d: d['columns'][3].update(property='x'), '$.columns[3].property'),
                                 (lambda d: d['columns'][0].update(name='GUID'), '$.columns[0].name'), (lambda d: d['columns'][0].update(name='\\N'), '$.columns[0].name'),
                                 (lambda d: d['columns'][0].update(property='id'), '$.columns[0].property'), (lambda d: d.update(columns=d['columns'][:1]), None)):
            document = example('ifcopenshell-baseline.json');change(document)
            self.fault(lambda: adaptor.plan(document), 'INVALID_COLUMN' if location else 'INVALID_ARGUMENT', location)
        document = example('ifcopenshell-metre.json');document['inheritance'] = 'occurrence-overrides-type'
        self.fault(lambda: adaptor.plan(document), 'INVALID_COLUMN', '$.inheritance')

    def test_baseline_oracle_literals(self):
        expected, p = schedule(fixture('walls-baseline.ifc'))
        self.assertEqual((expected['schema'], expected['counts']['walls'], expected['counts']['entities']), ('IFC4', 3, 34))
        self.assertEqual([r['guid'] for r in expected['rows']], ['0SYN000000000000000011', '0SYN000000000000000014', '0SYN000000000000000021'])
        got = [[r['name']] + [(c['origin'], c['value']) for c in r['cells']] for r in expected['rows']]
        self.assertEqual(got, [
            ['North wall', ('type', '2HR'), ('type', 'true'), ('missing', None), ('occurrence', 2.5), ('occurrence', 3.0)],
            ['Core wall', ('occurrence', '1HR'), ('type', 'true'), ('occurrence', '+reviewed =later'), ('occurrence', 4.0), ('missing', None)],
            [None, ('occurrence', '0123'), ('missing', None), ('occurrence', '007'), ('occurrence', 1.8), ('occurrence', 2.7)]])
        self.assertEqual(expected['units'], {'LENGTHUNIT': {'prefix': 'MILLI', 'name': 'METRE'}})

    def test_inheritance_policy_changes_origin_not_guessing(self):
        document = example('ifcopenshell-baseline.json');document['inheritance'] = 'occurrence-only'
        expected, _ = schedule(fixture('walls-baseline.ifc'), document)
        self.assertEqual([[c['origin'] for c in r['cells'][:2]] for r in expected['rows']], [['missing', 'missing'], ['occurrence', 'missing'], ['occurrence', 'missing']])

    def test_missing_policy_refuses_with_guid_and_never_zero(self):
        document = example('ifcopenshell-baseline.json');document['missing'] = 'refuse'
        fault = self.fault(lambda: schedule(fixture('walls-baseline.ifc'), document), 'MISSING_VALUE', '#8.columns[2]')
        self.assertEqual(fault.observed['guid'], '0SYN000000000000000011')
        expected, _ = schedule(fixture('walls-baseline.ifc'))
        self.assertNotIn(0.0, [c['value'] for r in expected['rows'] for c in r['cells'] if c['origin'] == 'missing'])

    def test_unit_conversion_exact_for_prefixed_area_and_volume(self):
        expected, _ = schedule(fixture('walls-areas.ifc'), example('ifcopenshell-areas.json'))
        self.assertEqual([[c['value'] for c in r['cells']] for r in expected['rows']], [['false', 0.0, 2.5, 7.5, 1.5], ['false', 0.0, 0.0, 1.5, 0.25]])
        self.assertEqual(expected['units']['AREAUNIT'], {'prefix': 'MILLI', 'name': 'SQUARE_METRE'})
        metre, _ = schedule(fixture('walls-metre.ifc'), example('ifcopenshell-metre.json'))
        self.assertEqual([[c['value'] for c in r['cells']] for r in metre['rows']], [[2.5, 3.0], [4.0, 2.4]])
        zero = example('ifcopenshell-areas.json');zero['zeroQuantity'] = 'refuse'
        self.fault(lambda: schedule(fixture('walls-areas.ifc'), zero), 'QUANTITY_ZERO')

    def test_exact_rounding_of_lexemes(self):
        self.assertEqual(step.exact_float(step.Fraction('2500.') * step.Fraction(10) ** -3, 'x'), 2.5)
        self.assertEqual(step.exact_float(step.Fraction('0.1'), 'x'), 0.1)
        self.assertEqual(step.exact_float(step.Fraction('1E-300') * step.Fraction(10) ** -3, 'x'), 1e-303)
        self.fault(lambda: step.exact_float(step.Fraction('1E-400'), 'x'), 'NUMBER_RANGE')
        self.fault(lambda: step.exact_float(step.Fraction('1E+400'), 'x'), 'NUMBER_RANGE')
        self.assertEqual(step.exact_float(step.Fraction('4.9E-324'), 'x'), 5e-324)

    def test_typed_csv_bytes_and_calc_consumer_parse(self):
        expected, p = schedule(fixture('walls-baseline.ifc'))
        files, schedule_json = adaptor.documents(p, {'sha256': '0' * 64, 'bytes': 1}, expected, {'ifcopenshell': '0.9.0.post1', 'python': '3.12.14', 'wrapperSha256': '1' * 64})
        self.assertEqual(files['ifc-schedule.csv'].decode(),
            '"GUID","Name","Fire rating","External","Note","Length (m)","Height (m)"\n'
            '"0SYN000000000000000011","North wall","2HR","true",\\N,2.5,3.0\n'
            '"0SYN000000000000000014","Core wall","1HR","true","+reviewed =later",4.0,\\N\n'
            '"0SYN000000000000000021",\\N,"0123",\\N,"007",1.8,2.7\n')
        columns = [{'name': c['header'], 'kind': c['kind'], 'nullable': c['nullable']} for c in schedule_json['columns']]
        table = typed_table.parse_csv(files['ifc-schedule.csv'], columns, '\\N')
        self.assertEqual(table['rows'][1], ['0SYN000000000000000014', 'Core wall', '1HR', 'true', '+reviewed =later', 4.0, None])
        self.assertEqual(schedule_json['numericPresent'], {'Length (m)': 3, 'Height (m)': 2})
        self.assertFalse(schedule_json['review']['geometryAssessed']);self.assertEqual(schedule_json['unassessed']['geometry'], 'unassessed')

    def test_text_with_quotes_stays_literal(self):
        text = fixture('walls-baseline.ifc').replace("'North wall'", "'Say \"hi\" O''Neil'")
        expected, p = schedule(text)
        self.assertEqual(expected['rows'][0]['name'], 'Say "hi" O\'Neil')
        files, _ = adaptor.documents(p, {'sha256': '0' * 64, 'bytes': 1}, expected, {'ifcopenshell': '0.9.0.post1', 'python': '3.12.14', 'wrapperSha256': '1' * 64})
        self.assertIn('"Say ""hi"" O\'Neil"', files['ifc-schedule.csv'].decode())

    def test_refusals_before_native(self):
        wall = "IFCWALL('0SYN000000000000000014'"
        self.mutate(wall, "IFCWALL('0SYN000000000000000011'", 'DUPLICATE_GLOBAL_ID', '#13.GlobalId')
        self.mutate('#9=IFCQUANTITYLENGTH', '#8=IFCQUANTITYLENGTH', 'DUPLICATE_ENTITY_ID', '#8')
        self.mutate('(#9,#10)', '(#9,#99)', 'DANGLING_REFERENCE', '#11.members[1]')
        self.mutate("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('IFC2X3'))", 'UNSUPPORTED_SCHEMA', 'header.FILE_SCHEMA')
        self.mutate("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('IFC4X3_ADD2'))", 'UNSUPPORTED_SCHEMA')
        self.mutate("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('IFC4','IFC2X3'))", 'UNSUPPORTED_SCHEMA')
        self.mutate("'North wall'", "'N\\X2\\00E9\\X0\\'", 'UNSUPPORTED_STEP_ESCAPE')
        self.mutate("'North wall'", "'Né'", 'UNSUPPORTED_STEP_ESCAPE')
        self.mutate("'North wall'", "'Tab\there'", 'UNSUPPORTED_STEP_ESCAPE')
        self.mutate('DATA;\n', 'DATA;\n/* note */\n', 'UNSUPPORTED_STEP_COMMENT')
        self.mutate('#8=IFCWALL(', '#8=IFCWALLSTANDARDCASE(', 'UNSUPPORTED_ENTITY_CLASS')
        self.mutate('ENDSEC;\nEND', '#40=IFCRELDEFINESBYTYPE(\'0SYN000000000000000040\',$,$,$,(#8),#7);\nENDSEC;\nEND', 'AMBIGUOUS_TYPE', '#8')
        self.mutate('ENDSEC;\nEND', "#40=IFCRELDEFINESBYPROPERTIES('0SYN000000000000000040',$,$,$,(#13),#6);\nENDSEC;\nEND", 'DUPLICATE_SET_NAME', 'Name', )
        self.mutate('(#4,#5)', '(#4,#4)', 'DUPLICATE_PROPERTY_NAME', '#4')
        self.mutate('.LENGTHUNIT.', '.TIMEUNIT.', 'UNIT_MISSING')
        self.mutate('#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)', "#1=IFCCONVERSIONBASEDUNIT(*,.LENGTHUNIT.,'INCH',$)", 'UNSUPPORTED_UNIT')
        self.mutate('.MILLI.,.METRE.', '.MICRO.,.METRE.', 'UNSUPPORTED_UNIT')
        self.mutate('.MILLI.,.METRE.', '.MILLI.,.FOOT.', 'UNSUPPORTED_UNIT')
        self.mutate('#2=IFCUNITASSIGNMENT((#1))', "#40=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n#2=IFCUNITASSIGNMENT((#1,#40))", 'UNIT_AMBIGUOUS')
        self.mutate('2500.', '-2500.', 'QUANTITY_NEGATIVE', '#9')
        self.mutate("IFCQUANTITYLENGTH('Length',$,$,2500.,$)", "IFCQUANTITYLENGTH('Length',$,#1,2500.,$)", 'UNSUPPORTED_QUANTITY_UNIT', '#9')
        self.mutate("IFCQUANTITYLENGTH('Length',$,$,2500.,$)", "IFCQUANTITYAREA('Length',$,$,2500.,$)", 'TYPE_MISMATCH', '#9')
        self.mutate("IFCLABEL('2HR')", 'IFCREAL(2.5)', 'TYPE_MISMATCH', '#4')
        self.mutate("IFCLABEL('2HR')", "IFCLABEL('')", 'UNREPRESENTABLE_EMPTY_TEXT', '#4')
        self.mutate("IFCLABEL('2HR'),$", "IFCLABEL('2HR'),#1", 'UNSUPPORTED_PROPERTY_UNIT', '#4')
        self.mutate("IFCLABEL('2HR')", '$', 'UNSUPPORTED_NULL_VALUE', '#4')
        self.mutate("IFCLABEL('2HR')", 'IFCLABEL(IFCTEXT(\'x\'))', 'TYPE_MISMATCH')
        self.mutate("IFCBOOLEAN(.T.)", "IFCLOGICAL(.U.)", 'TYPE_MISMATCH', '#5')
        self.mutate('IFCPROJECT(', 'IFCSITE(', 'PROJECT_AMBIGUOUS')
        self.mutate("'North wall',$,$,$,$,$,.STANDARD.", "'North wall',$,$,$,$,.STANDARD.", 'UNSUPPORTED_ENTITY_SHAPE', '#8')

    def test_wall_count_and_structure_budgets(self):
        text = fixture('walls-baseline.ifc')
        self.fault(lambda: schedule(text.replace('#13=IFCWALL(', '#13=IFCDOOR(').replace('#23=IFCWALL(', '#23=IFCDOOR(')), 'WALL_COUNT')
        self.fault(lambda: step.parse(b'x' * (step.MAX_BYTES + 1)), 'STEP_RESOURCE_LIMIT')
        self.fault(lambda: step.parse(text.replace('(#8,#13)', '(' + '(' * 10 + '#8' + ')' * 10 + ')').encode()), 'STEP_RESOURCE_LIMIT')
        self.fault(lambda: step.parse(text.replace('(#8,#13)', '(' + ','.join(['#8'] * 300) + ')').encode()), 'STEP_RESOURCE_LIMIT')
        self.fault(lambda: step.parse(text.replace("'North wall'", "'" + 'x' * 300 + "'").encode()), 'STEP_RESOURCE_LIMIT')
        self.fault(lambda: step.parse((text.replace('ENDSEC;\nEND-ISO-10303-21;\n', '') + '\n'.join(f'#{n}=IFCCARTESIANPOINT((0.,0.,0.));' for n in range(100, 100 + 4100)) + '\nENDSEC;\nEND-ISO-10303-21;\n').encode()), 'STEP_RESOURCE_LIMIT')
        self.fault(lambda: step.parse(b''), 'STEP_SYNTAX')
        self.fault(lambda: step.parse(text.replace('#1=IFCSIUNIT(', '#1=(IFCSIUNIT(*)').encode()), 'UNSUPPORTED_COMPLEX_ENTITY')
        self.fault(lambda: step.parse(text.replace('END-ISO-10303-21;', 'END-ISO-10303-21;\nextra').encode()), 'STEP_SYNTAX')
        self.fault(lambda: step.parse(text.replace("FILE_SCHEMA(('IFC4'));\n", '').encode()), 'STEP_HEADER')

    def test_unselected_entities_are_counted_not_assessed(self):
        text = fixture('walls-baseline.ifc').replace('ENDSEC;\nEND', "#50=IFCCARTESIANPOINT((0.,0.,0.));\n#51=IFCDOOR('0SYN000000000000000050',$,'Door',$,$,$,$,$,$,$,$);\nENDSEC;\nEND")
        expected, p = schedule(text)
        _, document = adaptor.documents(p, {'sha256': '0' * 64, 'bytes': 1}, expected, {'ifcopenshell': '0.9.0.post1', 'python': '3.12.14', 'wrapperSha256': '1' * 64})
        self.assertEqual(document['unassessed']['entityClasses'], {'IFCCARTESIANPOINT': 1, 'IFCDOOR': 1})

    def native_table(self, expected, p):
        rows = []
        for r in expected['rows']:
            cells = []
            for cell, column in zip(r['cells'], p['columns']):
                if cell['origin'] == 'missing': cells.append({'origin': 'missing', 'raw': None, 'value': None})
                elif column['source'] == 'quantity': cells.append({'origin': cell['origin'], 'raw': float(cell['sourceLexeme']), 'value': cell['value']})
                else:
                    value = {'true': True, 'false': False}.get(cell['value'], cell['value'])
                    cells.append({'origin': cell['origin'], 'raw': value, 'value': value})
            rows.append({'guid': r['guid'], 'name': r['name'], 'typeGuid': r['typeGuid'], 'cells': cells})
        return {'version': 'schemaxis.ifcopenshell.native/1', 'identity': {}, 'schema': 'IFC4', 'scales': {'LENGTHUNIT': 0.001}, 'rows': rows}

    def test_native_comparison_stops_every_semantic_drift(self):
        expected, p = schedule(fixture('walls-baseline.ifc'))
        native = self.native_table(expected, p)
        adaptor.check_native(copy.deepcopy(native), expected, p, 'native-extract.json')
        def drift(change, location):
            table = copy.deepcopy(native);change(table)
            self.fault(lambda: adaptor.check_native(table, expected, p, 'native-extract.json'), 'NATIVE_DISAGREES', location)
        drift(lambda t: t['rows'][0].update(guid='0SYN000000000000000099'), 'rows[0].guid')
        drift(lambda t: t['rows'][2].update(name='Other'), 'rows[2].name')
        drift(lambda t: t['rows'][0]['cells'][0].update(origin='occurrence'), 'rows[0].cells[0].origin')
        drift(lambda t: t['rows'][1]['cells'][0].update(value='2HR'), 'rows[1].cells[0].value')
        drift(lambda t: t['rows'][0]['cells'][1].update(value=False), 'rows[0].cells[1].value')
        drift(lambda t: t['rows'][0]['cells'][3].update(value=2.5000001), 'rows[0].cells[3].value')
        drift(lambda t: t['rows'][0]['cells'][3].update(raw=2501.0), 'rows[0].cells[3].value')
        drift(lambda t: t['rows'][1]['cells'][4].update(origin='occurrence', raw=0.0, value=0.0), 'rows[1].cells[4].origin')
        drift(lambda t: t['rows'][2]['cells'][0].update(origin='missing'), 'rows[2].cells[0].origin')
        drift(lambda t: t['rows'][2]['cells'][3].update(value=1.8 * (1 + 8e-16)), 'rows[2].cells[3].value')
        drift(lambda t: t.update(schema='IFC2X3'), '.schema')
        drift(lambda t: t['rows'].pop(), '.rows')
        # every retained native field is bound: type identity, unit scales and the raw source values with strict cell types
        drift(lambda t: t['rows'][0].update(typeGuid='0SYN0000000000000000ZZ'), 'rows[0].typeGuid')
        drift(lambda t: t['rows'][2].update(typeGuid='0SYN000000000000000002'), 'rows[2].typeGuid')
        drift(lambda t: t['scales'].update(LENGTHUNIT=1.0), 'scales.LENGTHUNIT')
        drift(lambda t: t['scales'].update(AREAUNIT=1e-06), '.scales')
        drift(lambda t: t['scales'].pop('LENGTHUNIT'), '.scales')
        drift(lambda t: t['scales'].update(LENGTHUNIT=True), 'scales.LENGTHUNIT')
        drift(lambda t: t['rows'][1]['cells'][0].update(raw='9HR'), 'rows[1].cells[0].raw')
        drift(lambda t: t['rows'][1]['cells'][1].update(raw=1), 'rows[1].cells[1].raw')
        drift(lambda t: t['rows'][0]['cells'][1].update(raw=False), 'rows[0].cells[1].raw')
        drift(lambda t: t['rows'][2]['cells'][4].update(raw=2.7), 'rows[2].cells[4]')
        # missing is not zero: a native zero where the oracle found nothing is a disagreement
        drift(lambda t: t['rows'][1]['cells'][4].update(raw=0.0, value=0.0), 'rows[1].cells[4]')
        # two-ulp native rounding is accepted, three is not
        near = copy.deepcopy(native);near['rows'][0]['cells'][3]['value'] = 2.5 + 4.4e-16
        adaptor.check_native(near, expected, p, 'native-extract.json')

    def test_number_types_and_booleans_are_strict_in_native_raw(self):
        text = fixture('walls-areas.ifc')
        expected, p = schedule(text, example('ifcopenshell-areas.json'))
        count = p['columns'][1]
        self.assertEqual((count['name'], count['valueType']), ('Count', 'number'))
        self.assertEqual(expected['rows'][0]['cells'][1]['sourceLexeme'], '0')
        self.assertEqual(expected['scaleExponents'], {'AREAUNIT': -6, 'LENGTHUNIT': -3, 'VOLUMEUNIT': -9})
        native = {'version': 'schemaxis.ifcopenshell.native/1', 'identity': {}, 'schema': 'IFC4', 'scales': {'AREAUNIT': 1e-06, 'LENGTHUNIT': 0.001, 'VOLUMEUNIT': 1e-09}, 'rows': []}
        for r in expected['rows']:
            cells = []
            for cell, column in zip(r['cells'], p['columns']):
                if column['source'] == 'quantity': cells.append({'origin': cell['origin'], 'raw': float(cell['sourceLexeme']), 'value': cell['value']})
                elif column['valueType'] == 'boolean': cells.append({'origin': cell['origin'], 'raw': cell['value'] == 'true', 'value': cell['value'] == 'true'})
                else: cells.append({'origin': cell['origin'], 'raw': int(cell['sourceLexeme']), 'value': int(cell['sourceLexeme'])})
            native['rows'].append({'guid': r['guid'], 'name': r['name'], 'typeGuid': r['typeGuid'], 'cells': cells})
        adaptor.check_native(copy.deepcopy(native), expected, p, 'n')
        for change in (lambda t: t['rows'][0]['cells'][1].update(raw=0.0), lambda t: t['rows'][0]['cells'][1].update(raw=False), lambda t: t['rows'][0]['cells'][1].update(value=0.0),
                       lambda t: t['rows'][0]['cells'][0].update(raw=0), lambda t: t['scales'].update(AREAUNIT=1e-03), lambda t: t['scales'].update(VOLUMEUNIT=1e-06)):
            table = copy.deepcopy(native);change(table)
            self.fault(lambda: adaptor.check_native(table, expected, p, 'n'), 'NATIVE_DISAGREES')

    # ------------------------------------------------------------ numeric and reference lexical budget
    PROBE = ('import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom schemaxis.adaptors.ifcopenshell import adaptor, step\nfrom schemaxis.core.faults import SchemaxisError\n'
             'document = json.loads(sys.argv[2])\ntry:\n    step.resolve(step.parse(sys.stdin.buffer.read()), adaptor.plan(document))\n    print(json.dumps({"ok": True}))\n'
             'except SchemaxisError as error:\n    print(json.dumps({"ok": False, "fault": error.fault.to_dict()}))\n')

    def probe(self, text, document=None, deadline=20):
        """Parse and resolve in an owned subprocess with a hard deadline; the process is always killed and reaped."""
        document = document or example('ifcopenshell-baseline.json')
        process = subprocess.Popen([sys.executable, '-I', '-c', self.PROBE, str(ROOT / 'src'), json.dumps(document)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try: out, err = process.communicate(text.encode(), timeout=deadline)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate()
            self.fail('host STEP reader exceeded its deadline: an unbounded numeric or reference conversion')
        self.assertEqual(process.returncode, 0, err.decode()[-400:])
        return json.loads(out)

    def refused_by_budget(self, text, location, document=None):
        result = self.probe(text, document)
        self.assertFalse(result['ok'], result)
        fault = result['fault']
        self.assertEqual((fault['code'], fault['location']), ('STEP_RESOURCE_LIMIT', location), fault)
        self.assertLess(len(json.dumps(fault)), 1200, 'the fault must stay bounded for a hostile token')
        return fault

    def test_numeric_and_reference_lexical_budget_in_every_placement(self):
        base = fixture('walls-baseline.ifc')
        hostile = ['1.E30000000', '1.E999999999', '1.E-30000000', '0.E999999999', '-0.E+999999999', '1.E+401', '1.E-401', '1.E00001', '1' + '0' * 40 + '.', '1.' + '0' * 40,
                   '9' * 4301, '-' + '9' * 4301, '+' + '9' * 4301, '2.' + '0' * 5000, '1.E' + '9' * 4301, '1.E-' + '9' * 4301, '1.E+' + '0' * 4301 + '1']
        placements = {
            'header': lambda token: base.replace("FILE_NAME('synthetic.ifc',", "FILE_NAME(" + token + ",", 1),
            'unselected': lambda token: base.replace('ENDSEC;\nEND', f'#50=IFCCARTESIANPOINT(({token},0.,0.));\nENDSEC;\nEND'),
            'nested': lambda token: base.replace('ENDSEC;\nEND', f'#50=IFCTHING((((({token})))));\nENDSEC;\nEND'),
            'selected-quantity': lambda token: base.replace('2500.', token),
            'selected-property': lambda token: base.replace("IFCLABEL('2HR')", f'IFCREAL({token})'),
        }
        document = example('ifcopenshell-baseline.json');document['columns'][0].update(valueType='number')
        for placement, build in placements.items():
            for token in hostile:
                with self.subTest(placement=placement, token=token[:24] + str(len(token))):
                    fault = self.refused_by_budget(build(token), '$.source.path', document)
                    if len(token) > 60: self.assertNotIn(token[:60], json.dumps(fault))

    def test_reference_digit_budget_in_header_data_and_entity_names(self):
        base = fixture('walls-baseline.ifc')
        self.refused_by_budget(base.replace('(#8,#13)', '(#' + '9' * 4301 + ',#13)'), '$.source.path')
        self.refused_by_budget(base.replace('#50=', '#50=').replace('ENDSEC;\nEND', '#' + '9' * 4301 + "=IFCTHING($);\nENDSEC;\nEND"), 'data')
        self.refused_by_budget(base.replace('ENDSEC;\nEND', '#' + '1' * 11 + "=IFCTHING($);\nENDSEC;\nEND"), 'data')
        self.refused_by_budget(base.replace('ENDSEC;\nEND', "#50=IFCTHING(#" + '0' * 11 + '1' + ");\nENDSEC;\nEND"), '$.source.path')

    def test_long_keyword_and_type_names_are_bounded_in_faults_with_a_location(self):
        base = fixture('walls-baseline.ifc')
        number = example('ifcopenshell-baseline.json');number['columns'][0].update(valueType='number')
        long_name = 'IFC' + 'Q' * 5000
        wall_name = 'IFCWALL' + 'Q' * 5000
        cases = [
            ('header duplicate', base.replace("FILE_SCHEMA(('IFC4'));", "FILE_SCHEMA(('IFC4'));" + long_name + '(1.);' + long_name + '(1.);'), None, 'STEP_HEADER', 'header'),
            ('wall subtype', base.replace('ENDSEC;\nEND', '#50=' + wall_name + '($);\nENDSEC;\nEND'), None, 'UNSUPPORTED_ENTITY_CLASS', 'data'),
            ('text nominal', base.replace("IFCLABEL('2HR')", long_name + "('2HR')"), None, 'TYPE_MISMATCH', '#4'),
            ('boolean nominal', base.replace('IFCBOOLEAN(.T.)', long_name + '(.T.)'), None, 'TYPE_MISMATCH', '#5'),
            ('number nominal', base.replace("IFCLABEL('2HR')", long_name + '(2.)'), number, 'TYPE_MISMATCH', '#4'),
            ('property class', base.replace('#4=IFCPROPERTYSINGLEVALUE(', '#4=' + long_name + '('), None, 'UNSUPPORTED_PROPERTY', '#4'),
            ('quantity class', base.replace('#9=IFCQUANTITYLENGTH(', '#9=' + long_name + '('), None, 'TYPE_MISMATCH', '#9'),
            ('related set class', base.replace('#11=IFCELEMENTQUANTITY(', '#11=' + long_name + '('), None, 'UNSUPPORTED_ENTITY_CLASS', '#12.RelatingPropertyDefinition'),
        ]
        for label, text, document, code, location in cases:
            with self.subTest(label):
                fault = self.fault(lambda: schedule(text, document), code, location)
                shown = json.dumps(fault.to_dict())
                self.assertLess(len(shown), 1200, shown[:300])
                name = wall_name if label == 'wall subtype' else long_name
                self.assertNotIn(name[:60], shown)
                prefix = 'IFCWALL' + 'Q' * 41 if label == 'wall subtype' else 'IFC' + 'Q' * 45  # the literal first 48 characters
                self.assertEqual(48, len(prefix))
                self.assertIn(f'{prefix}... ({len(name)} characters)', shown)
                self.assertIn(prefix, fault.message)
                self.assertEqual(fault.observed['nameCharacters'], len(name), fault.observed)
                if label == 'header duplicate': self.assertEqual(text.encode().find(long_name.encode(), text.find(long_name) + 1), fault.observed['offset'])
                if label == 'wall subtype': self.assertEqual(fault.observed['reference'], 50)
        # ordinary long IFC4 class names are repeated whole, not shortened
        realistic = 'IFCSTRUCTURALLOADSINGLEDISPLACEMENTDISTORTION'
        fault = self.fault(lambda: schedule(base.replace("IFCLABEL('2HR')", realistic + "('2HR')")), 'TYPE_MISMATCH', '#4')
        self.assertIn(realistic, fault.message)
        self.assertEqual(fault.observed['observed'], realistic)
        self.assertNotIn('...', json.dumps(fault.to_dict()))

    def test_long_unit_enums_are_bounded_and_keep_the_unit_type_and_location(self):
        base = fixture('walls-baseline.ifc')
        short = self.fault(lambda: schedule(base.replace('.MILLI.,.METRE.', '.MICRO.,.METRE.')), 'UNSUPPORTED_UNIT', '$.columns[')
        self.assertEqual((short.observed['unit'], short.observed['prefix'], short.observed['name']), ('LENGTHUNIT', 'MICRO', 'METRE'))
        self.assertEqual((short.observed['prefixCharacters'], short.observed['nameCharacters']), (5, 5))
        for label, old, enum, key, other in (('prefix', '.MILLI.', 'P' * 5000, 'prefix', 'name'), ('name', '.METRE.', 'N' * 5000, 'name', 'prefix')):
            with self.subTest(label):
                text = base.replace(old, f'.{enum}.', 1)
                fault = self.fault(lambda: schedule(text), 'UNSUPPORTED_UNIT', short.location)
                shown = json.dumps(fault.to_dict())
                self.assertLess(len(shown), 1200, shown[:300])
                self.assertNotIn(enum[:60], shown)
                self.assertEqual(fault.observed[key], enum[:48] + '... (5000 characters)')
                self.assertEqual(fault.observed[key + 'Characters'], 5000)
                self.assertEqual(fault.observed['unit'], 'LENGTHUNIT')
                self.assertEqual(fault.observed[other], 'METRE' if other == 'name' else 'MILLI')

    def test_wrong_argument_count_names_the_class_and_stays_bounded(self):
        for old, new, name, count, location in (
                ('#1=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)', '#1=IFCSIUNIT(*,.LENGTHUNIT.,.METRE.)', 'IFCSIUNIT', 4, '#2.Units[0]'),
                ("'Synthetic wall schedule',$,$,$,$,$,#2)", "'Synthetic wall schedule',$,$,$,$,#2)", 'IFCPROJECT', 9, '#3'),
                ("#8=IFCWALL('0SYN000000000000000011',$,'North wall',$,$,$,$,$,.STANDARD.)", "#8=IFCWALL('0SYN000000000000000011',$,'North wall',$,$,$,$,.STANDARD.)", 'IFCWALL', 9, '#8')):
            with self.subTest(name):
                fault = self.mutate(old, new, 'UNSUPPORTED_ENTITY_SHAPE', location)
                self.assertEqual(f'{name} must have {count} arguments in IFC4', fault.message)
                self.assertLess(len(json.dumps(fault.to_dict())), 600)

    def test_budget_boundary_values_stay_supported(self):
        for token in ('1.E400', '1.E-400', '1.' + '0' * 39, '9' * 40, '0.000000000000000000000000000000000000001', '-0.E+400', '+1.5E+0003'):
            number = step.Number(token)
            self.assertEqual(number.lexeme, token)
        self.assertEqual(step.reference('#' + '9' * 10, 'x'), 9999999999)
        text = fixture('walls-baseline.ifc')
        self.assertEqual(self.probe(text.replace('ENDSEC;\nEND', '#9999999999=IFCCARTESIANPOINT((1.E400,1.E-400,' + '9' * 40 + '.));\nENDSEC;\nEND'))['ok'], True)
        # budget-accepted but not representable: the semantic range refusals are unchanged
        for token, code in (('1.E400', 'NUMBER_RANGE'), ('1.E-400', 'NUMBER_RANGE')):
            document = example('ifcopenshell-baseline.json');document['columns'][0].update(valueType='number')
            result = self.probe(text.replace("IFCLABEL('2HR')", f'IFCREAL({token})'), document)
            self.assertEqual((result['ok'], result['fault']['code']), (False, 'NUMBER_RANGE'), result)
        self.assertEqual(step.exact_float(step.Number('4.9E-324').exact, 'x'), 5e-324)
        self.assertEqual(step.exact_float(step.Number('2500.').exact * step.Fraction(10) ** -3, 'x'), 2.5)

    def test_malformed_scientific_syntax_is_refused_with_a_clear_cause(self):
        text = fixture('walls-baseline.ifc')
        for token in ('25E2', '1.e5', '2.5e+3', '1E5', '1.E', '1.5E+'):
            with self.subTest(token=token):
                result = self.probe(text.replace('ENDSEC;\nEND', f'#50=IFCCARTESIANPOINT(({token}));\nENDSEC;\nEND'))
                self.assertFalse(result['ok'])
                self.assertEqual(result['fault']['code'], 'STEP_SYNTAX', result)

    def test_quantity_and_real_wrappers_need_part21_real_syntax(self):
        self.mutate('2500.', '2500', 'TYPE_MISMATCH', '#9')
        self.mutate('2500.', '25E2', 'STEP_SYNTAX')
        expected, _ = schedule(fixture('walls-baseline.ifc').replace('2500.', '2.5E3'))
        self.assertEqual(expected['rows'][0]['cells'][3]['value'], 2.5)
        document = example('ifcopenshell-baseline.json');document['columns'][0].update(valueType='number')
        self.mutate("IFCLABEL('2HR')", 'IFCREAL(2500)', 'TYPE_MISMATCH', '#4', document=document)
        self.mutate("IFCLABEL('2HR')", 'IFCREAL(25E2)', 'STEP_SYNTAX', document=document)
        self.mutate("IFCLABEL('2HR')", 'IFCINTEGER(2.)', 'TYPE_MISMATCH', '#4', document=document)
        expected, _ = schedule(fixture('walls-baseline.ifc').replace("IFCLABEL('2HR')", 'IFCINTEGER(7)').replace("IFCLABEL('1HR')", 'IFCINTEGER(8)').replace("IFCLABEL('0123')", 'IFCINTEGER(9)'), document)
        self.assertEqual([(c['cells'][0]['value'], c['cells'][0]['sourceLexeme']) for c in expected['rows']], [(7.0, '7'), (8.0, '8'), (9.0, '9')])

    def test_public_run_never_calls_a_hostile_numeric_source_a_native_failure(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            document = example('ifcopenshell-baseline.json')
            for label, token in (('exponent', '1.E30000000'), ('digits', '9' * 4301), ('exponent-zero', '0.E999999999')):
                source = scratch / (label + '.ifc')
                source.write_text(fixture('walls-baseline.ifc').replace('ENDSEC;\nEND', f'#50=IFCCARTESIANPOINT(({token}));\nENDSEC;\nEND'))
                document['source']['path'] = str(source)
                with mock.patch.object(adaptor, 'execute', side_effect=AssertionError('a native process was launched')) as native:
                    fault = self.fault(lambda: adaptor.run(document, scratch / ('run-' + label), executable='/bin/true', timeout=30), 'STEP_RESOURCE_LIMIT', '$.source.path')
                self.assertEqual(native.call_count, 0)
                self.assertEqual(sorted(p.name for p in (scratch / ('run-' + label)).glob('*-submission.json')), [])
                self.assertEqual(json.loads((scratch / ('run-' + label) / 'result.json').read_text())['fault']['code'], 'STEP_RESOURCE_LIMIT')
                self.assertLess(len(json.dumps(fault.to_dict())), 1200)
            # an unexpected host failure before any launch is not labelled a native failure
            source = scratch / 'ok.ifc';source.write_text(fixture('walls-baseline.ifc'));document['source']['path'] = str(source)
            with mock.patch.object(adaptor.step, 'resolve', side_effect=ZeroDivisionError('boom')), mock.patch.object(adaptor, 'execute', side_effect=AssertionError('launched')):
                self.fault(lambda: adaptor.run(document, scratch / 'run-host', executable='/bin/true', timeout=30), 'HOST_EXECUTION_FAILED')

    def test_verify_reports_a_hostile_stored_source_as_verification_failed_with_a_bounded_cause(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch) / 'retained';scratch.mkdir()
            source = fixture('walls-baseline.ifc').replace('ENDSEC;\nEND', '#50=IFCCARTESIANPOINT((1.E30000000));\nENDSEC;\nEND').encode()
            document = example('ifcopenshell-baseline.json');p = adaptor.plan(document)
            (scratch / 'authored.json').write_text(json.dumps(document));(scratch / 'plan.json').write_text(json.dumps(p))
            (scratch / 'source.ifc').write_bytes(source)
            info = {'sha256': adaptor.sha(source), 'bytes': len(source)}
            (scratch / 'captures.json').write_text(json.dumps({'source': p['source']['path'], **info}))
            (scratch / 'verification.json').write_text(json.dumps({'executable': '/x', 'runtime': adaptor.RUNTIME, 'planSha256': adaptor.plan_hash(p), 'artifacts': [], 'evidence': {}}))
            fault = self.fault(lambda: adaptor.verify(scratch, require_result=False), 'VERIFICATION_FAILED', '$.source.path')
            self.assertEqual(fault.observed['cause']['code'], 'STEP_RESOURCE_LIMIT')
            self.assertIn('STEP_RESOURCE_LIMIT', fault.message)
            self.assertLess(len(json.dumps(fault.to_dict())), 2000)

    def test_ordinary_ifc_unit_powered_conversions_still_exact(self):
        expected, _ = schedule(fixture('walls-areas.ifc'), example('ifcopenshell-areas.json'))
        self.assertEqual(expected['rows'][0]['cells'][2:], [{'column': 'Length (m)', 'origin': 'occurrence', 'value': 2.5, 'sourceLexeme': '2500.'},
                                                           {'column': 'Side area (m2)', 'origin': 'occurrence', 'value': 7.5, 'sourceLexeme': '7500000.'},
                                                           {'column': 'Volume (m3)', 'origin': 'occurrence', 'value': 1.5, 'sourceLexeme': '1500000000.'}])

    # ------------------------------------------------------------ property-only schedules and number representation
    def property_only(self):
        document = example('ifcopenshell-baseline.json');document['columns'] = document['columns'][:2]
        return document

    def test_property_only_schedule_does_not_need_project_units(self):
        text = fixture('walls-baseline.ifc').replace("'Synthetic wall schedule',$,$,$,$,$,#2)", "'Synthetic wall schedule',$,$,$,$,$,$)")
        expected, _ = schedule(text, self.property_only())
        self.assertEqual((expected['units'], expected['unitsUnassessed'], expected['scaleExponents']), ({}, 0, {}))
        self.assertEqual([[c['value'] for c in r['cells']] for r in expected['rows']], [['2HR', 'true'], ['1HR', 'true'], ['0123', None]])
        # a selected quantity without any project units is a structured unit fault, not a dangling reference
        self.fault(lambda: schedule(text), 'UNIT_MISSING', '$.columns[3]')
        # a reference that is present but undefined stays a dangling reference even for a property-only schedule
        self.fault(lambda: schedule(fixture('walls-baseline.ifc').replace("$,$,$,$,$,#2)", "$,$,$,$,$,#99)"), self.property_only()), 'DANGLING_REFERENCE', '#3.UnitsInContext')

    def test_number_representation_and_consumer_contract(self):
        document = example('ifcopenshell-baseline.json');document['columns'][0].update(valueType='number')
        text = fixture('walls-baseline.ifc').replace("IFCLABEL('2HR')", 'IFCINTEGER(7)').replace("IFCLABEL('1HR')", 'IFCREAL(1.E16)').replace("IFCLABEL('0123')", 'IFCINTEGER(9)')
        expected, p = schedule(text, document)
        self.assertEqual([r['cells'][0]['value'] for r in expected['rows'][:2]], [7.0, 1e16])
        files, schedule_json = adaptor.documents(p, {'sha256': '0' * 64, 'bytes': 1}, expected, {'ifcopenshell': '0.9.0.post1', 'python': '3.12.14', 'wrapperSha256': '1' * 64})
        rows = files['ifc-schedule.csv'].decode().split('\n')
        self.assertIn(',7.0,"true"', rows[1].replace('"North wall"', ''));self.assertIn(',1e+16,', rows[2])
        columns = [{'name': c['header'], 'kind': c['kind'], 'nullable': c['nullable']} for c in schedule_json['columns']]
        table = typed_table.parse_csv(files['ifc-schedule.csv'], columns, '\\N')
        self.assertEqual((table['rows'][0][2], table['rows'][1][2]), (7.0, 1e16))
        # a value the IFC standalone range accepts but Calc's typed table refuses is the consumer's check, made before the native Calc step
        big = fixture('walls-baseline.ifc').replace("IFCLABEL('2HR')", 'IFCREAL(1.E101)').replace("IFCLABEL('1HR')", 'IFCINTEGER(8)').replace("IFCLABEL('0123')", 'IFCINTEGER(9)')
        expected, p = schedule(big, document)
        files, schedule_json = adaptor.documents(p, {'sha256': '0' * 64, 'bytes': 1}, expected, {'ifcopenshell': '0.9.0.post1', 'python': '3.12.14', 'wrapperSha256': '1' * 64})
        self.assertIn(',1e+101,', files['ifc-schedule.csv'].decode())
        columns = [{'name': c['header'], 'kind': c['kind'], 'nullable': c['nullable']} for c in schedule_json['columns']]
        with self.assertRaises(SchemaxisError) as raised: typed_table.parse_csv(files['ifc-schedule.csv'], columns, '\\N')
        self.assertEqual((raised.exception.fault.code, raised.exception.fault.message), ('INVALID_TABLE', 'number cells must be finite numbers within +/-1e100'))

    def test_native_identity_pins_the_lookup_and_unit_modules(self):
        self.assertEqual(sorted(adaptor.NATIVE_MODULES), ['util/element.py', 'util/unit.py'])
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            identity = {'ifcopenshell': '0.9.0.post1', 'python': '3.12.14', 'wrapper': 'w.so', 'wrapperBytes': 1, 'wrapperSha256': '1' * 64, 'modules': dict(adaptor.NATIVE_MODULES)}
            (scratch / 'version.stdout').write_text(json.dumps(identity));self.assertEqual(adaptor.identity_of(scratch)['modules'], adaptor.NATIVE_MODULES)
            identity['modules']['util/unit.py'] = '2' * 64
            (scratch / 'version.stdout').write_text(json.dumps(identity))
            self.fault(lambda: adaptor.identity_of(scratch), 'UNSUPPORTED_NATIVE_VERSION', 'version.modules')
            del identity['modules'];(scratch / 'version.stdout').write_text(json.dumps(identity))
            self.fault(lambda: adaptor.identity_of(scratch), 'UNSUPPORTED_NATIVE_VERSION', 'version')

    def test_launcher_binds_inputs_and_fixes_environment(self):
        p = adaptor.plan(example('ifcopenshell-baseline.json'))
        command = adaptor.commands('/venv/bin/python', p)
        self.assertEqual(command['extract'][:3], ['/venv/bin/python', '-I', 'worker.py'])
        self.assertNotEqual(command['extract'], command['reopen'])
        text = adaptor.launcher(Path('.'), 'extract', command['extract'], p)
        for needle in ('source.ifc', 'intent.json', 'worker.py', 'O_NOFOLLOW', 'RLIMIT_AS', 'execve'): self.assertIn(needle, text)
        self.assertNotIn('expected', adaptor.WORKER_SOURCE.read_text().split('def extract')[1].replace('expected', '', 0) if False else adaptor.encode_json(adaptor.intent_of(p)).decode())

    def test_discovery_and_planning_never_import_the_native_library(self):
        code = ('import sys\nsys.path.insert(0, %r)\n'
                'import schemaxis.adaptors.ifcopenshell.adaptor as a, schemaxis.adaptors.ifcopenshell.step as s, schemaxis.adaptors.ifcopenshell.capabilities as c\n'
                'a.plan(%r); c.catalogue()\nassert "ifcopenshell" not in sys.modules, sorted(m for m in sys.modules if "ifcopenshell" in m and not m.startswith("schemaxis"))\n'
                'assert "numpy" not in sys.modules\n') % (str(ROOT / 'src'), example('ifcopenshell-baseline.json'))
        done = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_run_refuses_before_any_native_launch(self):
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            source = scratch / 'duplicate.ifc'
            source.write_text(fixture('walls-baseline.ifc').replace("IFCWALL('0SYN000000000000000014'", "IFCWALL('0SYN000000000000000011'"))
            document = example('ifcopenshell-baseline.json');document['source']['path'] = str(source)
            fault = self.fault(lambda: adaptor.run(document, scratch / 'run', executable='/bin/true', timeout=30), 'DUPLICATE_GLOBAL_ID', '#13.GlobalId')
            self.assertEqual(sorted(p.name for p in (scratch / 'run').glob('*-submission.json')), [])
            self.assertEqual(json.loads((scratch / 'run/result.json').read_text())['status'], 'failed')
            self.assertFalse((scratch / 'run/ifc-schedule.csv').exists())
            self.fault(lambda: adaptor.run(document, scratch / 'run2', executable='python', timeout=30), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.run(document, scratch / 'run3', executable='/bin/true', timeout=0), 'INVALID_ARGUMENT')
            pinned = example('ifcopenshell-baseline.json');pinned['source'].update(path=str(source), sha256='0' * 64)
            self.fault(lambda: adaptor.run(pinned, scratch / 'run4', executable='/bin/true', timeout=30), 'SOURCE_HASH_MISMATCH', '$.source.sha256')
            self.fault(lambda: adaptor.run(document, scratch / 'run', executable='/bin/true', timeout=30), 'OUTPUT_EXISTS')
            link = scratch / 'link.ifc';link.symlink_to(source)
            missing = copy.deepcopy(document);missing['source']['path'] = str(scratch / 'absent.ifc')
            self.fault(lambda: adaptor.run(missing, scratch / 'run5', executable='/bin/true', timeout=30), 'INVALID_SOURCE', '$.source.path')

    def test_every_reviewed_search_case_resolves_in_the_live_catalogue(self):
        from schemaxis.capabilities import CapabilityCatalogue
        catalogue = CapabilityCatalogue()
        cases = json.loads((ROOT / 'src/schemaxis/adaptors/ifcopenshell/search-cases.json').read_text())
        self.assertGreaterEqual(len(cases), 10)
        for case in cases:
            found = {item['id'] for item in catalogue.search(case['query'])['items']}
            present = 'operation/ifcopenshell/scheduleWalls' in found
            self.assertEqual(present, case['kind'] != 'negative', (case['id'], sorted(found)[:5]))


if __name__ == '__main__': unittest.main()
