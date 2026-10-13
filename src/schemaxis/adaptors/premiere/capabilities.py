"""Bounded guidance without claiming native Premiere qualification."""
def catalogue():
    return {'groups': {'inspection': {'label': 'Sequence observation', 'purpose': 'Check the active sequence against declared source ranges.', 'domain': 'media'}},
            'requirements': ['Experimental integration; installed Premiere native acceptance remains pending.',
                             'Windows/macOS Premiere 26.5+, UDT 2.2+ and the supplied read-only UXP panel.',
                             'Exact saved project identity and idle active sequence; explicit fresh job folder selection.',
                             'Source contents, effects and rendered pixels are unverified.'],
            'references': ['docs/premiere.md', 'src/schemaxis/adaptors/premiere/readiness.json'],
            'operations': {'sequenceContract': {'purpose': 'Observe exact native sequence/clip ticks and source identities against declared ranges; no native mutation.',
                                              'groups': ['inspection'], 'semantics': ['Experimental integration; native acceptance remains pending.',
                                                  'Two matching bounded observations are not an atomic snapshot.',
                                                  'Source contents, effects and rendered pixels are not checked.']}}}
