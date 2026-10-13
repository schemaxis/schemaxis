"""Trusted built-in view contracts; authored files cannot provide UI code."""
import copy
from .errors import fail

PANELS = {
    'geometry': {'representation': 'native-tessellation/1', 'accepts': ['geometry'],
                 'selections': ['native-subelement'], 'access': 'annotation'},
    'image': {'representation': 'png/1', 'accepts': ['image'],
              'selections': ['image-pixel'], 'access': 'annotation'},
    'text': {'representation': 'utf8-text/1', 'accepts': ['text'],
             'selections': ['text-span'], 'access': 'annotation', 'pageLimit': 16384},
    'table': {'representation': 'csv-table/1', 'accepts': ['table'],
              'selections': ['table-range'], 'access': 'annotation', 'pageLimit': 100},
    'series': {'representation': 'numeric-series/1', 'accepts': ['table'],
               'selections': ['series-interval'], 'access': 'annotation', 'pageLimit': 200,
               'requirements': 'Explicit numeric x/y columns; finite values and strictly increasing x.'},
    'workflow': {'representation': 'workflow-graph/1', 'accepts': ['workflow'],
                 'selections': ['workflow-operation'], 'access': 'authored-edit',
                 'actions': ['source', 'patch', 'rewire'], 'requirements': 'Validated workflow; edges are declared artifact handoffs.'},
    'source': {'representation': 'authored-json/1', 'accepts': ['document'],
               'selections': ['json-pointer'], 'access': 'authored-edit', 'actions': ['source', 'patch']},
    'context': {'representation': 'typed-references/1', 'accepts': ['reference'],
                'selections': [], 'access': 'annotation'},
}
PRESETS = {
    'workflow-study': {'label': 'Workflow study', 'panels': ['workflow', 'source', 'context'],
                       'limitations': 'Host plan and authored handoffs; native artifact verification happens during execution.'},
    'geometry-study': {'label': 'Geometry study', 'panels': ['geometry', 'image', 'source', 'context']},
    'text-inspection': {'label': 'Text inspection', 'panels': ['text', 'source', 'context'],
                        'limitations': 'Inspection only. Extraction stages await the supplied tool contract.'},
    'table-analysis': {'label': 'Tables and signals', 'panels': ['table', 'series', 'source', 'context'],
                       'limitations': 'Read-only CSV and explicit numeric columns; no spreadsheet formula engine.'},
}


def catalogue():
    return copy.deepcopy({'version': 'schemaxis.views/1', 'panels': PANELS, 'presets': PRESETS})


def preset(identity):
    if not isinstance(identity, str) or identity not in PRESETS:
        fail('UNKNOWN_WORKSPACE', 'choose a trusted built-in workspace', choices=list(PRESETS))
    return copy.deepcopy(PRESETS[identity])
