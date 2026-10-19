"""Curated report publication discovery."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'Pandoc','purpose':'Publish structured reports as standalone HTML and editable Word DOCX with independently checked semantic retention.','keywords':['document converter','report publication','Word','DOCX','HTML']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':['Declare an ordered section outline, plain paragraphs, rectangular text tables and optional local plain PNG images.',
            'Replace each image path with an absolute regular RGB/RGBA PNG. Images are captured before native execution.',
            'Only the bounded report model is supported; arbitrary Markdown, HTML, filters, templates and scripts are excluded.'],
        'references':['docs/pandoc.md','src/schemaxis/adaptors/pandoc/readiness.json'],
        'operations':{'report':{'purpose':'Publish a structured Word report and standalone HTML document, preserving declared section order, headings, paragraphs, table cells and embedded PNG imagery.',
            'keywords':['Word report','DOCX','standalone HTML','document','report','section','heading','table','local image','Pandoc JSON AST'],
            'semantics':['Trusted JSON AST maps directly to public Header/Para/Table/Image constructors; no authored code.',
                'Both generated documents and fresh native DOCX readback are independently checked against authored report values.'],
            'examples':[{'reference':'examples/schemaxis/pandoc-report.json','purpose':'A calibration report with an ordered outline, measured table and local PNG.'},
                {'reference':'examples/schemaxis/pandoc-report-variant.json','purpose':'Change a cell, image display width and heading level to exercise semantic retention.'}]}}}
