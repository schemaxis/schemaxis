# Copyright (C) 2026 David L. F. Gaden.
"""Calc workbook source-node identity; no native imports.

The single table node is a zero-input source with no graph input container.
Column labels, CSV paths, cells, requirement names and the fixed Data/Summary
sheet names are workbook data, not node references, so none is declared.
The name pattern equals the literal schema and the planner's whole-string rule.
"""
from schemaxis.identity_policy import VERSION

NODE_NAME = {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_]{0,63}(?![\\s\\S])'}


def policy():
    return {'version': VERSION,
            'identities': [{'name': 'node', 'form': 'array-property', 'collection': ['nodes'],
                            'nameProperty': 'id', 'nameSchema': dict(NODE_NAME),
                            'graph': {'discriminator': 'filter', 'inputs': None}}],
            'references': [], 'markers': [], 'expressions': {}}
