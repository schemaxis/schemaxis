"""Prospective aggregate limits for the separate mixed physical-union engine."""
from dataclasses import dataclass

from schemaxis.errors import fail
from schemaxis.dispatch import remaining_timeout

LIMITS = {'pieces': 512, 'faces': 8192, 'edges': 16384,
          'booleans': 2048, 'facePairs': 2000000}


def preflight(**counts):
    """Counts are compiled geometry costs, never authored permission to skip work."""
    if set(counts) != set(LIMITS):
        fail('RESOURCE_LIMIT', 'Mixed replay needs every aggregate cost before geometry allocation')
    for key, limit in LIMITS.items():
        value = counts[key]
        if type(value) is not int or not 0 <= value <= limit:
            fail('RESOURCE_LIMIT', 'Mixed physical replay exceeds its prospective aggregate budget', key,
                 requested=value, limit=limit)
    remaining_timeout()
    return dict(counts)


@dataclass
class BooleanBudget:
    operations: int = 0
    face_pairs: int = 0
    identity_checks: int = 0

    def check(self):
        """Bound cumulative native membership and endpoint comparisons too."""
        remaining_timeout()
        if self.identity_checks >= LIMITS['facePairs']:
            fail('RESOURCE_LIMIT', 'Mixed source topology comparison budget exhausted')
        self.identity_checks += 1

    def before(self, left_faces, right_faces):
        remaining_timeout()
        if any(type(n) is not int or not 0 <= n <= LIMITS['faces'] for n in (left_faces, right_faces)):
            fail('RESOURCE_LIMIT', 'Boolean operand face count exceeds mixed replay admission')
        operations = self.operations+1
        pairs = self.face_pairs+left_faces*right_faces
        if operations > LIMITS['booleans'] or pairs > LIMITS['facePairs']:
            fail('RESOURCE_LIMIT', 'Mixed Boolean work exceeds its cumulative budget',
                 operations=operations, facePairs=pairs)
        # A refused operation never consumes budget or reaches the kernel.
        self.operations, self.face_pairs = operations, pairs

    def after(self, faces, edges):
        remaining_timeout()
        for key, value in (('faces', faces), ('edges', edges)):
            if type(value) is not int or not 0 <= value <= LIMITS[key]:
                fail('RESOURCE_LIMIT', 'Mixed Boolean result exceeds its topology budget', key,
                     requested=value, limit=LIMITS[key])
