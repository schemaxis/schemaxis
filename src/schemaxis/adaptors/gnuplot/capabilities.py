# Copyright (C) 2026 David L F Gaden
"""Scientific numeric plotting discovery, without native imports."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'Gnuplot','purpose':'Create scientific plots from named CSV columns with units, explicit linear/logarithmic axes and error bars.','keywords':['scientific plot','CSV','error bars','logarithmic','SVG','PNG']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':['Declare an absolute local numeric CSV, exact named columns and units, series mappings and explicit axis ranges.',
            'Require increasing x samples, positive log data/error endpoints and matching column/axis units.',
            'Only the bounded scientific plot model is supported; no authored commands, arbitrary expressions or options.'],
        'references':['docs/gnuplot.md','src/schemaxis/adaptors/gnuplot/readiness.json'],
        'operations':{'plot':{'purpose':'Draw scientific plot series with optional error bars and linear or logarithmic axes, publishing SVG, PNG, captured CSV and editable trusted script.',
            'keywords':['scientific plot','error bars','logarithmic','plot','CSV','scatter','line chart','uncertainty','SVG','PNG','Gnuplot'],
            'semantics':['Named numeric columns map to axes with matching declared units. Explicit ranges contain all samples and uncertainty endpoints.',
                'Trusted script drives native Gnuplot; independent SVG geometry and PNG series pixels are checked against captured numeric values.'],
            'examples':[{'reference':'examples/schemaxis/gnuplot-calibration.json','purpose':'Plot measured calibration with absolute symmetric y uncertainty.'},{'reference':'examples/schemaxis/gnuplot-logarithmic.json','purpose':'Plot positive data and uncertainty endpoints on log10 axes.'}]}}}
