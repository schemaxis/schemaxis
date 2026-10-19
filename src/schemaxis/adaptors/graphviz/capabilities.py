"""Host-only discovery of automatic directed graph layout."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'Graphviz','purpose':'Automatically lay out directed dependency diagrams and feedback flow graphs from named topology.','keywords':['Graphviz','directed graph','dependency diagram','automatic layout','DOT','DAG']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':['Declare all named nodes and directed edges; DAG policy rejects feedback, cyclic policy permits it.',
            'Select native dot 16.1.0; no external graph files, arbitrary DOT, images, URLs, HTML labels or native flags.'],
        'references':['docs/graphviz.md','src/schemaxis/adaptors/graphviz/readiness.json'],
        'operations':{'layout':{'purpose':'Create an automatic layout of a directed graph or dependency diagram with fixed boxes, routed splines, editable DOT, SVG and checked geometry.',
            'keywords':['automatic layout','dependency diagram','directed graph','DAG','feedback','flowchart','dot','Graphviz','topology','branch','reconvergence'],
            'semantics':['Literal named-node and directed-edge multiplicity is preserved. Fixed box geometry uses inches, SVG uses points and inverted y.',
                'TB top-to-bottom and LR left-to-right DAG ranks are checked independently; cyclic flows have no forward-rank guarantee.'],
            'examples':[{'reference':'examples/schemaxis/graphviz-baseline.json','purpose':'Lay out a branch and reconvergence as four named tasks.'},{'reference':'examples/schemaxis/graphviz-cycle.json','purpose':'Explicitly permit a feedback loop.'}]}}}
