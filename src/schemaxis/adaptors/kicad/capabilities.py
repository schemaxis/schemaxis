"""Operation selection guidance for saved KiCad boards checked by kicad-cli."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'KiCad',
                'purpose': 'Inspect saved KiCad printed circuit boards, run the native design rule check and export '
                           'Excellon drill files, each independently checked against the board geometry.',
                'keywords': ['PCB', 'printed circuit board', 'EDA', 'kicad-cli', 'electronics layout']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': [
            'Supply an absolute path to a saved two-copper-layer .kicad_pcb (KiCad 8.0-10.0 format). A sibling .kicad_pro '
            'or .kicad_dru with the same name is captured with it; global library tables are never used.',
            'Lengths are millimetres; drill files may be written in millimetres or inches. Board coordinates are KiCad '
            'y-down; Excellon coordinates are y-up with the absolute board origin.',
            'This slice reads and checks existing boards. It does not author boards, refill zones or compare with a schematic.',
            'DRC passes only when actual native error, warning and unconnected counts stay within the authored maximums; '
            'exceeding them fails the run with DRC_VIOLATIONS and blocks publication and reuse.',
            'Keep board-summary.json with the native report or drill files: it records host cross-checks, unchecked '
            'aspects and losses.'],
        'references': ['docs/kicad.md', 'src/schemaxis/adaptors/kicad/readiness.json'],
        'operations': {
            'inspectBoard': {
                'purpose': 'Count footprints, pads, vias, nets, holes and the board outline of a saved board and confirm '
                           'them against KiCad\'s own board statistics report.',
                'keywords': ['board statistics', 'pad count', 'hole count', 'board size', 'outline dimensions',
                             'inventory'],
                'related': ['designRuleCheck', 'drillExport'],
                'semantics': ['Host reader counts are compared with kicad-cli pcb export stats; any disagreement fails verification.',
                              'Minimum track clearance follows KiCad\'s statistic: different-net tracks/vias on each item\'s primary layer.'],
                'examples': [{'reference': 'examples/schemaxis/kicad-inspect.json',
                              'purpose': 'Inspect the 30 x 20 mm two-layer fixture with four footprints and six holes.'}]},
            'designRuleCheck': {
                'purpose': 'Run KiCad\'s native design rule check on a saved board and accept it only within authored '
                           'maximum error, warning and unconnected counts.',
                'keywords': ['DRC', 'design rules', 'clearance violation', 'unconnected', 'ratsnest', 'rule check',
                             'manufacturability'],
                'related': ['inspectBoard', 'drillExport'],
                'semantics': ['Uses the board\'s own project rules and severities; ignored checks are listed in the summary.',
                              'Host geometry independently predicts track/via clearance breaches and missing pad '
                              'connections on simple boards; other findings are native-only.'],
                'examples': [{'reference': 'examples/schemaxis/kicad-drc.json',
                              'purpose': 'Require zero errors, warnings and unconnected items on the clean fixture.'}]},
            'drillExport': {
                'purpose': 'Export Excellon drill files for fabrication after a passing DRC and match every drill hit '
                           'to a board hole by position, diameter and plating.',
                'keywords': ['drill file', 'Excellon', 'NC drill', 'fabrication output', 'PTH', 'NPTH', 'plated holes',
                             'manufacturing'],
                'related': ['designRuleCheck', 'inspectBoard'],
                'semantics': ['Absolute origin and decimal coordinates; plated and non-plated holes are separate files '
                              'unless separatePlating is false.',
                              'Round holes on F.Cu-B.Cu only; slots, offsets, backdrills, blind/buried vias and drill maps are unsupported.'],
                'examples': [{'reference': 'examples/schemaxis/kicad-drill.json',
                              'purpose': 'Separate PTH/NPTH millimetre drill files for the baseline fixture.'},
                             {'reference': 'examples/schemaxis/kicad-drill-variant.json',
                              'purpose': 'One merged inch drill file for the 40 x 25 mm variant with nine holes.'}]}}}
