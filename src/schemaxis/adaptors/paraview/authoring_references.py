# Copyright (C) 2026 David L. F. Gaden.
"""ParaView authored node identities and references; no native imports.

Native option text (calculator expressions, selectors, arrays and filenames) is
not a graph reference. Generated graph/writer ports come from their declarations.
"""
from schemaxis.identity_policy import VERSION, ARRAY
from schemaxis.schema import NODE_NAME


def policy():
    def reference(path, shape='scalar'):
        return {'identity': 'node', 'path': path, 'shape': shape}
    return {'version': VERSION,
            'identities': [{'name': 'node', 'form': 'array-property', 'collection': ['nodes'],
                            'nameProperty': 'id', 'nameSchema': dict(NODE_NAME),
                            'graph': {'discriminator': 'filter', 'inputs': 'inputs'}}],
            'references': [reference(['times', 'source']),
                           reference(['scenes', ARRAY, 'visible'], 'keys'),
                           reference(['scenes', ARRAY, 'appearances', ARRAY], 'keys'),
                           reference(['scenes', ARRAY, 'geometry'], 'list'),
                           reference(['scenes', ARRAY, 'measurements', ARRAY, 'node']),
                           reference(['scenes', ARRAY, 'exports', ARRAY, 'node']),
                           {**reference(['scenes', ARRAY, 'exports', ARRAY, 'resources'], 'writer-resources'),
                            'discriminator': 'writer'}],
            'markers': [{'key': key, 'identity': 'node'} for key in ('$observe', '$sample', '$object')],
            'expressions': {'extents': 'node'}}
