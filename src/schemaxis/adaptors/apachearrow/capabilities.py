"""Curated nullable-table and Parquet interchange discovery."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'Apache Arrow',
            'purpose': 'Prepare typed nullable CSV tables for portable Parquet interchange, preserving exact identifiers and UTC timestamps.',
            'keywords': ['Apache Arrow', 'PyArrow', 'Parquet', 'typed CSV', 'nullable table']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['Isolated Python >=3.11 with PyArrow 26.0.0 on POSIX.',
                         'Bounded UTF-8 CSV with every column type and nullability declared.'],
        'references': ['docs/apachearrow.md', 'src/schemaxis/adaptors/apachearrow/readiness.json'],
        'operations': {'prepareTable': {
            'purpose': 'Filter, select, rename and prepare an explicitly typed nullable table as independently verified Parquet and a readable report.',
            'keywords': ['Parquet', 'PyArrow', 'Apache Arrow', 'typed CSV', 'nullable table',
                         'column projection', 'wide integer identifiers', 'UTC timestamps', 'missing values', 'null fill'],
            'semantics': ['Keep source row order, exact wide integers, Unicode text, null masks and UTC microseconds.',
                          'Only declared int32-to-int64 widening and explicit null replacement; no arbitrary expressions or metadata.'],
            'examples': [{'reference': 'examples/schemaxis/apachearrow-measurements.json', 'purpose': 'Preserve typed nullable measurements.'},
                         {'reference': 'examples/schemaxis/apachearrow-selection.json', 'purpose': 'Filter accepted rows and prepare selected columns.'}]}}
    }
