# Copyright (C) 2026 David L. F. Gaden.
"""Owner-local asset names and every ordered clip occurrence; no native authority."""
from schemaxis.identity_policy import LOCAL_VERSION

ASSET_NAME = {'type': 'string', 'minLength': 1, 'maxLength': 64,
              'pattern': r'^[A-Za-z][A-Za-z0-9_-]{0,63}(?![\s\S])'}


def policy():
    return {'version': LOCAL_VERSION,
            'identities': [{'name': 'asset', 'form': 'owner-array-property',
                            'owner': {'path': ['nodes', {'each': 'array'}],
                                      'discriminator': {'property': 'filter', 'value': 'editTimeline'}},
                            'collection': ['options', 'assets'], 'nameProperty': 'name',
                            'nameSchema': dict(ASSET_NAME)}],
            'references': [{'identity': 'asset', 'scope': 'owner',
                            'path': ['options', 'clips', {'each': 'array'}, 'asset'], 'shape': 'scalar'}],
            'markers': [], 'expressions': {}}
