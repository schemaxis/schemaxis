# Copyright (C) 2026 David L F Gaden
"""Curated nullable-table and Parquet interchange discovery."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'Apache Arrow',
            'purpose': 'Prepare typed nullable CSV tables for portable Parquet interchange, with an optional declared-schema typed CSV publication, preserving exact identifiers and UTC timestamps.',
            'keywords': ['Apache Arrow', 'PyArrow', 'Parquet', 'typed CSV', 'nullable table']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['Isolated Python >=3.11 with PyArrow 26.0.0 on POSIX.',
                         'Bounded UTF-8 CSV with every column type and nullability declared.'],
        'references': ['docs/apachearrow.md', 'src/schemaxis/adaptors/apachearrow/readiness.json'],
        'operations': {'prepareTable': {
            'purpose': 'Filter, select, rename and prepare an explicitly typed nullable table as independently verified Parquet and a readable report, optionally also publishing the same rows as a canonical typed CSV whose consumer must declare the identical schema.',
            'keywords': ['Parquet', 'PyArrow', 'Apache Arrow', 'typed CSV', 'nullable table',
                         'column projection', 'wide integer identifiers', 'UTC timestamps', 'missing values', 'null fill',
                         'publishCSV', 'typed CSV publication', 'declared schema CSV handoff', 'null token'],
            'semantics': ['Keep source row order, exact wide integers, Unicode text, null masks and UTC microseconds.',
                          'Only declared int32-to-int64 widening and explicit null replacement; no arbitrary expressions or metadata.',
                          'Opt-in publishCSV adds a canonical table.csv at artifact 2; it has no type metadata, spells null as bare \\N and carries formula-looking text as literal data.'],
            'examples': [{'reference': 'examples/schemaxis/apachearrow-measurements.json', 'purpose': 'Preserve typed nullable measurements.'},
                         {'reference': 'examples/schemaxis/apachearrow-selection.json', 'purpose': 'Filter accepted rows and prepare selected columns.'},
                         {'reference': 'examples/schemaxis/apachearrow-csv-publication.json', 'purpose': 'Publish a filtered, renamed nullable table as typed CSV beside Parquet.'}]}}
    }
