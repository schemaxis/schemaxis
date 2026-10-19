"""KiCad board contracts, independent reader and falsification tests (host-only)."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from schemaxis.adaptor_conformance import host
from schemaxis.adaptors.kicad import adaptor, board, drc, drill
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'examples/schemaxis/fixtures/kicad'

# Hand-written KiCad 8 form of the baseline board, independent of the saved fixture.
LEGACY = textwrap.dedent('''\
    (kicad_pcb (version 20240108) (generator "test")
      (general (thickness 1.6))
      (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
      (net 0 "") (net 1 "SIG") (net 2 "GND")
      (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts"))
      (footprint "T:H" (layer "F.Cu") (at 3.5 3.5) (attr exclude_from_bom)
        (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask")))
      (footprint "T:J" (layer "F.Cu") (at 8 10 90) (property "Reference" "J1") (attr through_hole)
        (pad "1" thru_hole circle (at 0 0 90) (size 1.7 1.7) (drill 1.0) (layers "*.Cu") (net 1 "SIG"))
        (pad "2" thru_hole circle (at 0 2.54 90) (size 1.7 1.7) (drill 1.0) (layers "*.Cu") (net 2 "GND")))
      (segment (start 8 10) (end 8 6) (width 0.25) (layer "F.Cu") (net 1))
      (via (at 8 6) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))
      (segment (start 10.54 10) (end 10.54 14) (width 0.25) (layer "F.Cu") (net 2))
    )
    ''')


def document(name='drc', board_name='tiny-board'):
    d = json.loads((ROOT/f'examples/schemaxis/kicad-{name}.json').read_text())
    d['board'] = str(FIXTURES/(board_name+'.kicad_pcb'))
    return d


def fixture(name):
    return board.read(FIXTURES/(name+'.kicad_pcb'))


def code(action):
    with unittest.TestCase().assertRaises(SchemaxisError) as caught:
        action()
    return caught.exception.fault.code


def text_board(body, version='20260206', layers='(0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user)'):
    return f'(kicad_pcb (version {version}) (generator "test") (layers {layers}) {body})'


# Literal native statistics expected for tiny-board, written from its declared geometry.
STATS = {'board': {'has_outline': True, 'width': '30.0000 mm', 'height': '20.0000 mm', 'min_track_clearance': '1.6500 mm',
                   'min_track_width': '0.2500 mm', 'min_drill_diameter': '0.3000 mm', 'board_thickness': '1.6000 mm'},
         'pads': {'through_hole': 2, 'smd': 2, 'connector': 0, 'npth': 2, 'castellated': 0, 'press_fit': 0},
         'vias': {'through': 2, 'blind': 0, 'buried': 0, 'micro': 0},
         'components': {'tht': {'front': 1, 'back': 0}, 'smd': {'front': 1, 'back': 0}, 'unspecified': {'front': 2, 'back': 0}},
         'drill_holes': [{'count': 2, 'shape': 'Round', 'x_size': f'{d} mm', 'y_size': f'{d} mm', 'plated': p, 'source': s,
                          'start_layer': 'F.Cu', 'stop_layer': 'B.Cu'}
                         for d, p, s in (('3.2000', False, 'Pad'), ('1.0000', True, 'Pad'), ('0.3000', True, 'Via'))]}
PTH = 'M48\n; #@! TF.FileFunction,Plated,1,2,PTH\nFMAT,2\nMETRIC\n; #@! TA.AperFunction,Plated,PTH,ViaDrill\nT1C0.300\n' \
      '; #@! TA.AperFunction,Plated,PTH,ComponentDrill\nT2C1.000\n%\nG90\nG05\nT1\nX8.0Y-6.0\nX19.05Y-6.0\nT2\nX8.0Y-10.0\nX10.54Y-10.0\nM30\n'
NPTH = 'M48\n; #@! TF.FileFunction,NonPlated,1,2,NPTH\nFMAT,2\nMETRIC\n; #@! TA.AperFunction,NonPlated,NPTH,ComponentDrill\n' \
       'T1C3.200\n%\nG90\nG05\nT1\nX3.5Y-3.5\nX26.5Y-16.5\nM30\n'


def report(violations=(), unconnected=(), version='10.0.7'):
    return {'$schema': drc.SCHEMA, 'coordinate_units': 'mm', 'kicad_version': version, 'source': 'board.kicad_pcb',
            'included_severities': ['error', 'warning', 'exclusion'], 'ignored_checks': [], 'schematic_parity': [],
            'violations': list(violations), 'unconnected_items': list(unconnected)}


def clearance(actual):
    return {'type': 'clearance', 'severity': 'error',
            'description': f'Clearance violation ( clearance 0.2000 mm; actual {actual} mm)',
            'items': [{'description': 'Track [AUX] on F.Cu, length 4.0215 mm', 'pos': {'x': 15.5, 'y': 14.35}},
                      {'description': 'Track [GND] on F.Cu, length 10.4100 mm', 'pos': {'x': 15.5, 'y': 14.0}}]}


FAKE = '''#!{python}
"""Test-only stand-in for kicad-cli; it replays literal outputs and never computes them."""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
data = json.loads(Path({payload!r}).read_text())
if args == ['version']:
    print(data.get('version', '10.0.7')); sys.exit(0)
if args[:1] == ['version']:
    print('Application: kicad-cli test stand-in'); sys.exit(0)
board = Path(args[-1])
if data.get('mutate'):
    board.write_text(board.read_text() + ' ')
output = args[args.index('-o')+1]
if args[:3] == ['pcb', 'export', 'stats']:
    Path(output).write_text(json.dumps(data['stats']))
elif args[:2] == ['pcb', 'drc']:
    Path(output).write_text(json.dumps(data['drc']))
    print('Found %d violations' % len(data['drc']['violations']))
    print('Found %d unconnected items' % len(data['drc']['unconnected_items']))
elif args[:3] == ['pcb', 'export', 'drill']:
    for name, text in data['drill'].items():
        Path(output, name).write_text(text)
'''


class KicadAdmissionTests(unittest.TestCase):
    def test_host_conformance(self):
        self.assertTrue(host(adaptor.VERSION)['verified'])

    def test_plans_are_deterministic_and_reject_unsupported_requests(self):
        d = document('drill'); before = copy.deepcopy(d)
        self.assertEqual(adaptor.plan(d), adaptor.plan(d)); self.assertEqual(d, before)
        self.assertEqual(adaptor.plan(d)['publications'][-2:], ['drill/board-PTH.drl', 'drill/board-NPTH.drl'])
        self.assertEqual(adaptor.plan(document('drill-variant', 'tiny-variant'))['publications'][-1], 'drill/board.drl')
        cases = [({'board': 'relative.kicad_pcb'}, 'INVALID_RESOURCE'), ({'board': '/x/board.kicad_sch'}, 'INVALID_RESOURCE'),
                 ({'board': '/x/a\n.kicad_pcb'}, 'INVALID_RESOURCE'), ({'version': 'schemaxis.kicad/2'}, 'UNSUPPORTED_VERSION'),
                 ({'operation': 'autoroute'}, 'UNKNOWN_FILTER'), ({'script': 'print(1)'}, 'UNKNOWN_ARGUMENT'),
                 ({'maximumErrors': -1}, 'INVALID_ARGUMENT'), ({'maximumErrors': True}, 'INVALID_ARGUMENT'),
                 ({'maximumWarnings': 1.5}, 'INVALID_ARGUMENT'), ({'units': 'mil'}, 'INVALID_ARGUMENT'),
                 ({'separatePlating': 'yes'}, 'INVALID_ARGUMENT')]
        for change, expected in cases:
            bad = {**document('drill'), **change}
            with self.subTest(change=change):
                self.assertEqual(code(lambda: adaptor.plan(bad)), expected)
        # Drill options do not belong to a design rule check request.
        bad = {**document('drc'), 'units': 'mm'}
        self.assertNotEqual(code(lambda: adaptor.plan(bad)), '')

    def test_schema_accepts_examples_and_rejects_cross_operation_fields(self):
        import jsonschema
        schema = adaptor.schema()
        for name in ('inspect', 'drc', 'drill', 'drill-variant'):
            jsonschema.validate(document(name), schema)
        for bad in ({**document('inspect'), 'maximumErrors': 0}, {**document('drc'), 'units': 'in'},
                    {**document('drc'), 'maximumErrors': -1}):
            with self.subTest(bad=bad), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)

    def test_fixture_facts_follow_declared_geometry(self):
        facts = board.summary(fixture('tiny-board'))
        self.assertEqual(facts['formatVersion'], 20260206)
        self.assertEqual(facts['counts']['footprints'], 4); self.assertEqual(facts['counts']['holes'], 6)
        self.assertEqual(facts['nets'], ['GND', 'SIG'])
        self.assertEqual(facts['outline']['bounds_mm'], [0.0, 0.0, 30.0, 20.0])
        self.assertAlmostEqual(facts['minimumTrackClearance_mm'], 1.65, places=9)
        holes = sorted((h['x'], h['y'], h['diameter'], h['plated']) for h in fixture('tiny-board')['holes'])
        # J1 at (8, 10) rotated 90 degrees: local pad (0, 2.54) lands at (10.54, 10).
        self.assertIn((10540000, 10000000, 1000000, True), holes)
        variant = fixture('tiny-variant')
        # Rotated 270 degrees, the third pin (0, 5.08) lands at (2.92, 12.5).
        self.assertIn((2920000, 12500000), [(h['x'], h['y']) for h in variant['holes']])
        self.assertAlmostEqual(board.summary(variant)['minimumTrackClearance_mm'], 1.55, places=9)
        legacy = board.summary(board.model(board.parse(LEGACY)))
        self.assertEqual(legacy['counts']['pads']['throughHole'], 2); self.assertEqual(legacy['nets'], ['GND', 'SIG'])
        self.assertEqual(legacy['drillTable'], [{'count': 1, 'diameter_mm': 3.2, 'plated': False, 'source': 'pad'},
                                                {'count': 2, 'diameter_mm': 1.0, 'plated': True, 'source': 'pad'},
                                                {'count': 1, 'diameter_mm': 0.3, 'plated': True, 'source': 'via'}])

    def test_malformed_unknown_and_unsupported_boards_are_rejected(self):
        cases = [
            ('(kicad_pcb (version 20260206)', 'UNSUPPORTED_BOARD'), ('(kicad_pcb (version 20260206)))', 'UNSUPPORTED_BOARD'),
            ('(kicad_pcb (version 20260206) (generator "x)', 'UNSUPPORTED_BOARD'), ('(kicad_sch (version 20260206))', 'UNSUPPORTED_BOARD'),
            ('(kicad_pcb (version 20260206)) (kicad_pcb)', 'UNSUPPORTED_BOARD'), ('(kicad_pcb (generator "x"))', 'UNSUPPORTED_BOARD'),
            (text_board('', version='20270101'), 'UNSUPPORTED_BOARD'), (text_board('', version='20231120'), 'UNSUPPORTED_BOARD'),
            (text_board('', layers='(0 "F.Cu" signal) (4 "In1.Cu" signal) (6 "In2.Cu" signal) (2 "B.Cu" signal)'), 'UNSUPPORTED_BOARD'),
            (text_board('(via blind (at 1 1) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "A"))'), 'UNSUPPORTED_BOARD'),
            (text_board('(footprint "x" (layer "F.Cu") (at 1 1) (pad "1" thru_hole oval (at 0 0) (size 2 1) (drill oval 1.5 0.6) (layers "*.Cu")))'),
             'UNSUPPORTED_BOARD'),
            (text_board('(footprint "x" (layer "F.Cu") (at 1 1) (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1 (offset 0.2 0)) (layers "*.Cu")))'),
             'UNSUPPORTED_BOARD'),
            (text_board('(footprint "x" (layer "F.Cu") (at 1 1) (fp_line (start 0 0) (end 1 0) (layer "Edge.Cuts")))'), 'UNSUPPORTED_BOARD'),
            (text_board('(gr_curve (pts (xy 0 0) (xy 1 1) (xy 2 1) (xy 3 0)) (layer "Edge.Cuts"))'), 'UNSUPPORTED_BOARD'),
            (text_board('(segment (start 0 0) (end 1e9 0) (width 0.2) (layer "F.Cu") (net "A"))'), 'UNSUPPORTED_BOARD'),
            (text_board('(segment (start 0 0) (end nan 0) (width 0.2) (layer "F.Cu") (net "A"))'), 'UNSUPPORTED_BOARD'),
            (text_board('(footprint "x" (layer "F.Cu") (at 1 1 north))'), 'UNSUPPORTED_BOARD'),
            ('('*65+')'*65, 'RESOURCE_LIMIT'), ('(kicad_pcb '+'"'+'x'*(4*1024*1024)+'")', 'RESOURCE_LIMIT')]
        for text, expected in cases:
            with self.subTest(text=text[:80]):
                self.assertEqual(code(lambda: board.model(board.parse(text))), expected)
        many = text_board(' '.join(f'(via (at {i%100} {i//100}) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "N{i}"))'
                                   for i in range(2001)))
        self.assertEqual(code(lambda: board.model(board.parse(many))), 'RESOURCE_LIMIT')

    def test_arc_outline_bounds_and_unmodelled_arc_tracks(self):
        model = board.model(board.parse(text_board(
            '(gr_arc (start 10 0) (mid 0 10) (end -10 0) (layer "Edge.Cuts")) (gr_line (start -10 0) (end 10 0) (layer "Edge.Cuts"))'
            ' (arc (start 0 0) (mid 1 1) (end 2 0) (width 0.2) (layer "F.Cu") (net "A"))')))
        facts = board.summary(model)
        self.assertEqual(facts['outline']['bounds_mm'], [-10.0, 0.0, 10.0, 10.0])
        self.assertTrue(facts['trackClearanceStatus'].startswith('unchecked'))
        self.assertIsNone(drc.predict(model, drc.rules(None, False))['clearance'].get('breaches'))

    def test_native_statistics_disagreement_fails(self):
        facts = board.summary(fixture('tiny-board'))
        self.assertTrue(board.compare_statistics(facts, STATS)['drillTable'])
        for path, value in [(('board', 'width'), '30.1000 mm'), (('pads', 'npth'), 3), (('vias', 'through'), 1),
                            (('board', 'min_track_clearance'), '1.6000 mm'), (('components', 'tht', 'front'), 2),
                            (('board', 'has_outline'), False), (('board', 'width'), '30 mils')]:
            bad = copy.deepcopy(STATS); target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assertEqual(code(lambda: board.compare_statistics(facts, bad)), 'VERIFICATION_FAILED')
        bad = copy.deepcopy(STATS); bad['drill_holes'][0]['count'] = 3
        self.assertEqual(code(lambda: board.compare_statistics(facts, bad)), 'VERIFICATION_FAILED')

    def test_drc_report_validation_assessment_and_predictions(self):
        model = fixture('tiny-clearance')
        rule = drc.rules(json.loads((FIXTURES/'tiny-clearance.kicad_pro').read_text()), False)
        prediction = drc.predict(model, rule)
        self.assertEqual(prediction['clearance'], {'status': 'checked', 'breaches': 2, 'gaps_mm': [0.1, 0.1]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'drc.json'
            def load(value, version='10.0.7'):
                path.write_text(json.dumps(value)); return drc.read(path, version, 'board.kicad_pcb')
            native = load(report([clearance('0.1000'), clearance('0.1000')]))
            self.assertEqual(drc.cross_check(native, prediction), {'clearance': 'confirmed', 'unconnected': 'confirmed'})
            self.assertEqual(drc.assess(native, {'maximumErrors': 0, 'maximumWarnings': 0, 'maximumUnconnected': 0})['exceeded'], ['errors'])
            self.assertTrue(drc.assess(native, {'maximumErrors': 2, 'maximumWarnings': 0, 'maximumUnconnected': 0})['accepted'])
            # A forged clean or partial report, or a wrong gap, contradicts the host geometry.
            for forged in (report(), report([clearance('0.1000')]), report([clearance('0.1500'), clearance('0.1000')])):
                with self.subTest(forged=len(forged['violations'])):
                    self.assertEqual(code(lambda: drc.cross_check(load(forged), prediction)), 'VERIFICATION_FAILED')
            for change in ({'$schema': 'x'}, {'kicad_version': '9.0.1'}, {'source': 'other.kicad_pcb'},
                           {'included_severities': ['error']}, {'schematic_parity': [{}]}, {'coordinate_units': 'in'},
                           {'violations': [{'type': 'clearance', 'severity': 'fatal', 'description': '', 'items': []}]},
                           {'violations': [{'type': 'x', 'severity': 'error', 'description': '', 'items': [{'description': 'a', 'pos': {'x': 'nan'}}]}]}):
                with self.subTest(change=change):
                    self.assertEqual(code(lambda: load({**report(), **change})), 'VERIFICATION_FAILED')
            native = load(report())
            self.assertEqual(code(lambda: drc.console('Found 1 violations\nFound 0 unconnected items\n', native)), 'VERIFICATION_FAILED')
            drc.console('Found 0 violations\nFound 0 unconnected items\n', native)
        # Custom rules, several netclasses or a downgraded severity disable the clearance model.
        for settings, custom in (({}, True), ({'net_settings': {'classes': [{'name': 'Default'}, {'name': 'Power'}]}}, False),
                                 ({'board': {'design_settings': {'rule_severities': {'clearance': 'warning'}}}}, False)):
            self.assertFalse(drc.rules(settings, custom)['applicable'])

    def test_connectivity_counts_open_nets_and_marks_ambiguous_copper_unchecked(self):
        self.assertEqual(drc.connectivity(fixture('tiny-open')), (1, None))
        self.assertEqual(drc.connectivity(fixture('tiny-board')), (0, None))
        pad = '(footprint "x" (layer "F.Cu") (at {x} {y}) (pad "1" smd {shape} (at 0 0) (size {w} {h}) {extra}(layers "F.Cu") (net "N")))'
        # Same-net tracks crossing in their interiors have no endpoint contact.
        crossing = text_board(pad.format(x=-10, y=0, shape='circle', w=1, h=1, extra='')+pad.format(x=0, y=-10, shape='circle', w=1, h=1, extra='')
                              + '(segment (start -10 0) (end 10 0) (width 0.2) (layer "F.Cu") (net "N"))'
                              + '(segment (start 0 -10) (end 0 10) (width 0.2) (layer "F.Cu") (net "N"))')
        self.assertIsNone(drc.connectivity(board.model(board.parse(crossing)))[0])
        overlapping = text_board(pad.format(x=0, y=0, shape='circle', w=1, h=1, extra='')+pad.format(x=0.75, y=0, shape='circle', w=1, h=1, extra=''))
        self.assertIsNone(drc.connectivity(board.model(board.parse(overlapping)))[0])
        # An endpoint inside a rectangle's corner but outside its rounded corner does not anchor.
        corner = text_board(pad.format(x=0, y=0, shape='roundrect', w=2, h=2, extra='(roundrect_rratio 0.25) ')
                            + pad.format(x=5, y=0, shape='circle', w=1, h=1, extra='')
                            + '(segment (start 0.97 0.97) (end 5 0) (width 0.01) (layer "F.Cu") (net "N"))')
        self.assertEqual(drc.connectivity(board.model(board.parse(corner)))[0], None)
        square = corner.replace('roundrect', 'rect').replace('(roundrect_rratio 0.25) ', '')
        self.assertEqual(drc.connectivity(board.model(board.parse(square))), (0, None))

    def test_comparison_budget_reports_unchecked_instead_of_scanning(self):
        model = fixture('tiny-board')
        with patch.object(board, 'MAX_COMPARISONS', 0):
            self.assertEqual(board.gaps(model, 200000), (None, 'track/via comparison budget exceeded'))
            self.assertTrue(board.minimum_gap(model)[1].startswith('unchecked'))
            self.assertEqual(drc.connectivity(model), (None, 'connectivity comparison budget exceeded'))

    def test_drill_hits_must_match_board_holes(self):
        holes = fixture('tiny-board')['holes']
        with tempfile.TemporaryDirectory() as tmp:
            def read(pth=PTH, npth=NPTH, units='mm'):
                (Path(tmp)/'board-PTH.drl').write_text(pth); (Path(tmp)/'board-NPTH.drl').write_text(npth)
                return [drill.read(Path(tmp)/'board-PTH.drl', units), drill.read(Path(tmp)/'board-NPTH.drl', units)]
            result = drill.compare(holes, read(), 'mm', True)
            self.assertEqual((result['holes'], result['plated'], result['nonPlated']), (6, 4, 2))
            for label, pth, npth in [('flipped y', PTH.replace('X8.0Y-6.0', 'X8.0Y6.0'), NPTH),
                                     ('moved', PTH.replace('X19.05Y-6.0', 'X19.06Y-6.0'), NPTH),
                                     ('diameter', PTH.replace('T2C1.000', 'T2C1.100'), NPTH),
                                     ('missing', PTH.replace('X10.54Y-10.0\n', ''), NPTH),
                                     ('extra', PTH.replace('M30', 'X1.0Y-1.0\nM30'), NPTH),
                                     ('plating', PTH, NPTH.replace('NonPlated,NPTH,ComponentDrill', 'Plated,PTH,ComponentDrill')),
                                     ('role', PTH.replace('Plated,1,2,PTH', 'NonPlated,1,2,NPTH'), NPTH)]:
                with self.subTest(label=label):
                    self.assertEqual(code(lambda: drill.compare(holes, read(pth, npth), 'mm', True)), 'VERIFICATION_FAILED')
            self.assertEqual(code(lambda: read(PTH.replace('METRIC', 'INCH'))), 'VERIFICATION_FAILED')
            self.assertEqual(code(lambda: read(PTH.replace('G90', 'G91'))), 'VERIFICATION_FAILED')
            self.assertEqual(code(lambda: read(PTH.replace('X8.0Y-6.0', 'G85X8.0Y-6.0'))), 'VERIFICATION_FAILED')
            inch = PTH.replace('METRIC', 'INCH').replace('T1C0.300', 'T1C0.0118').replace('T2C1.000', 'T2C0.0394')
            inch = inch.replace('X8.0Y-6.0', 'X0.315Y-0.2362').replace('X19.05Y-6.0', 'X0.75Y-0.2362')
            inch = inch.replace('X8.0Y-10.0', 'X0.315Y-0.3937').replace('X10.54Y-10.0', 'X0.415Y-0.3937')
            npth = NPTH.replace('METRIC', 'INCH').replace('T1C3.200', 'T1C0.1260').replace('X3.5Y-3.5', 'X0.1378Y-0.1378')
            npth = npth.replace('X26.5Y-16.5', 'X1.0433Y-0.6496')
            self.assertEqual(drill.compare(holes, read(inch, npth, 'in'), 'in', True)['holes'], 6)

    def test_run_rejects_missing_or_unsupported_runtime_before_native_work(self):
        d = document('drc')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'KICAD_CLI': ''}), \
                patch('shutil.which', return_value=None):
            self.assertEqual(code(lambda: adaptor.run(d, Path(tmp)/'run')), 'INTERPRETER_NOT_FOUND')
            Path(tmp, 'exists').mkdir()
            self.assertEqual(code(lambda: adaptor.run(d, Path(tmp)/'exists', executable=sys.executable)), 'OUTPUT_EXISTS')
            self.assertEqual(code(lambda: adaptor.run(d, Path(tmp)/'t', executable=sys.executable, timeout=0)), 'INVALID_ARGUMENT')
            missing = {**d, 'board': str(Path(tmp)/'absent.kicad_pcb')}
            self.assertEqual(code(lambda: adaptor.run(missing, Path(tmp)/'m', executable=sys.executable)), 'RESOURCE_NOT_FOUND')
        self.assertEqual(code(lambda: adaptor.runtime('9.0.4\n')), 'UNSUPPORTED_RUNTIME')
        self.assertEqual(code(lambda: adaptor.runtime('10.1.0\n')), 'UNSUPPORTED_RUNTIME')
        self.assertEqual(adaptor.runtime('warning\n10.0.7\n')['version'], '10.0.7')

    def fake(self, tmp, **payload):
        data = {'stats': STATS, 'drc': report(), 'drill': {'board-PTH.drl': PTH, 'board-NPTH.drl': NPTH}, **payload}
        Path(tmp, 'payload.json').write_text(json.dumps(data))
        script = Path(tmp, 'kicad-cli')
        script.write_text(FAKE.format(python=sys.executable, payload=str(Path(tmp, 'payload.json'))))
        script.chmod(0o755)
        return str(script)

    def test_replayed_outputs_are_verified_and_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)/'run'
            result = adaptor.run(document('drill'), run, executable=self.fake(tmp), timeout=120)
            self.assertTrue(result['verified']); self.assertEqual(result['holes'], 6)
            self.assertEqual(json.loads((run/'board-summary.json').read_text())['drc']['crossCheck']['unconnected'], 'confirmed')
            self.assertFalse((FIXTURES/'tiny-board.kicad_prl').exists())
            for name in ('board-summary.json', 'drill/board-PTH.drl', 'board/board.kicad_pcb', 'board/board.kicad_pro', 'drc-report.json'):
                path = run/name; original = path.read_bytes()
                try:
                    path.write_bytes(original+b' ')
                    with self.subTest(name=name):
                        self.assertEqual(code(lambda: adaptor.verify(run)), 'VERIFICATION_FAILED')
                finally:
                    path.write_bytes(original)
            self.assertTrue(adaptor.verify(run)['verified'])

    def test_forged_clean_drc_mutation_and_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            # The stand-in claims the clearance fixture is clean; host geometry predicts two breaches.
            stats = copy.deepcopy(STATS)
            stats['board']['min_track_clearance'] = '0.1000 mm'
            stats['pads'].update(through_hole=4); stats['components']['tht']['front'] = 3
            stats['drill_holes'][1]['count'] = 4
            self.assertEqual(code(lambda: adaptor.run(document('drc', 'tiny-clearance'), Path(tmp)/'forged',
                                                      executable=self.fake(tmp, stats=stats), timeout=120)), 'VERIFICATION_FAILED')
            self.assertEqual(json.loads((Path(tmp)/'forged/result.json').read_text())['status'], 'failed')
            self.assertEqual(code(lambda: adaptor.run(document('drc'), Path(tmp)/'mutated',
                                                      executable=self.fake(tmp, mutate=True), timeout=120)), 'NATIVE_MUTATED_INPUT')
            self.assertEqual(code(lambda: adaptor.run(document('drc'), Path(tmp)/'old',
                                                      executable=self.fake(tmp, version='9.0.4'), timeout=120)), 'UNSUPPORTED_RUNTIME')
            gated = report([clearance('0.1000')])
            self.assertEqual(code(lambda: adaptor.run(document('drill'), Path(tmp)/'gated',
                                                      executable=self.fake(tmp, drc=gated), timeout=120)), 'VERIFICATION_FAILED')

    def test_board_inputs_are_regular_bounded_and_never_block(self):
        import signal
        with tempfile.TemporaryDirectory() as tmp:
            fifo = Path(tmp)/'pipe.kicad_pcb'; os.mkfifo(fifo)
            previous = signal.signal(signal.SIGALRM, lambda *_: self.fail('board input read blocked'))
            signal.alarm(10)
            try:
                self.assertEqual(code(lambda: adaptor.reusableInputs({**document('drc'), 'board': str(fifo)})), 'UNSUPPORTED_RESOURCE')
                plain = Path(tmp)/'plain.kicad_pcb'; plain.write_text(LEGACY)
                os.mkfifo(Path(tmp)/'plain.kicad_pro')
                self.assertEqual(code(lambda: adaptor.reusableInputs({**document('drc'), 'board': str(plain)})), 'UNSUPPORTED_RESOURCE')
            finally:
                signal.alarm(0); signal.signal(signal.SIGALRM, previous)
            large = Path(tmp)/'large.kicad_pcb'
            with large.open('wb') as stream:
                stream.truncate(board.MAX_BOARD_BYTES+1)
            self.assertEqual(code(lambda: adaptor.reusableInputs({**document('drc'), 'board': str(large)})), 'RESOURCE_LIMIT')
            link = Path(tmp)/'link.kicad_pcb'; link.symlink_to(FIXTURES/'tiny-board.kicad_pcb')
            self.assertEqual(code(lambda: adaptor.reusableInputs({**document('drc'), 'board': str(link)})), 'UNSUPPORTED_RESOURCE')
            absent = {**document('drc'), 'board': str(Path(tmp)/'absent.kicad_pcb')}
            self.assertEqual(code(lambda: adaptor.reusableInputs(absent)), 'RESOURCE_NOT_FOUND')
        digests = adaptor.reusableInputs(document('drc'))
        self.assertEqual(sorted(Path(p).name for p in digests), ['tiny-board.kicad_pcb', 'tiny-board.kicad_pro'])

    def test_stage_submissions_bind_exit_status_command_and_logs(self):
        from schemaxis.artifacts import atomic_json, file_digest
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)/'run'
            adaptor.run(document('drc'), run, executable=self.fake(tmp), timeout=120)
            def rehash():
                # A forger who also refreshes the evidence digests is still caught.
                receipt = json.loads((run/'verification.json').read_text())
                receipt['evidence'] = {n: file_digest(run/n) for n in receipt['evidence'] if (run/n).is_file()}
                atomic_json(run/'verification.json', receipt)
            record = run/'drc-submission.json'; original = record.read_bytes()
            log = run/'stats.stdout'; text = log.read_bytes()
            for label, change in [('exit', lambda r: r.update(exitCode=42)), ('command', lambda r: r.update(nativeCommand=['/bin/false'])),
                                  ('flag', lambda r: r['nativeCommand'].remove('--severity-all')),
                                  ('script', lambda r: r.update(scriptPath='/tmp/replay-x.py'))]:
                value = json.loads(original); change(value); record.write_text(json.dumps(value)); rehash()
                with self.subTest(label=label):
                    self.assertEqual(code(lambda: adaptor.verify(run)), 'VERIFICATION_FAILED')
                record.write_bytes(original)
            log.write_bytes(b'forged\n'); rehash()
            self.assertEqual(code(lambda: adaptor.verify(run)), 'VERIFICATION_FAILED')
            log.write_bytes(text); rehash()
            self.assertTrue(adaptor.verify(run)['verified'])
            for stage in ('version', 'about', 'stats', 'drc'):
                path = run/(stage+'-submission.json'); kept = path.read_bytes(); path.unlink()
                with self.subTest(missing=stage):
                    self.assertEqual(code(lambda: adaptor.verify(run)), 'VERIFICATION_FAILED')
                path.write_bytes(kept)
            self.assertTrue(adaptor.verify(run)['verified'])

    def test_unmet_maximum_fails_without_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            warning = {'type': 'track_dangling', 'severity': 'warning', 'description': 'Track has unconnected end',
                       'items': [{'description': 'Track [GND] on F.Cu, length 4.0000 mm', 'pos': {'x': 1, 'y': 1}}]}
            run = Path(tmp)/'run'
            self.assertEqual(code(lambda: adaptor.run(document('drill'), run, executable=self.fake(tmp, drc=report([warning])),
                                                      timeout=120)), 'DRC_VIOLATIONS')
            self.assertFalse((run/'drill').exists()); self.assertFalse((run/'verification.json').exists())
            summary = json.loads((run/'board-summary.json').read_text())
            self.assertEqual(summary['drc']['assessment']['exceeded'], ['warnings'])
            relaxed = {**document('drc'), 'maximumWarnings': 1}
            self.assertTrue(adaptor.run(relaxed, Path(tmp)/'relaxed', executable=self.fake(tmp, drc=report([warning])),
                                        timeout=120)['verified'])


if __name__ == '__main__':
    unittest.main()
