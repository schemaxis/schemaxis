"""Bounded guidance without claiming native Premiere qualification."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'Adobe Premiere Pro',
                        'purpose': 'Inspect an already open saved sequence using read-only UXP observation and declared editorial expectations.',
                        'keywords': ['Premiere', 'UXP', 'video editing', 'editorial', 'sequence inspection']},
        'groups': {'inspection': {'label': 'Sequence observation', 'purpose': 'Check the active sequence against declared source ranges and layout requirements.', 'domain': 'media'}},
        'requirements': ['Experimental integration; installed Premiere native acceptance remains pending.',
                         'Windows/macOS Premiere 26.5+, UDT 2.2+ and the supplied read-only UXP panel.',
                         'Exact saved project identity and idle active sequence; explicit fresh job folder selection.',
                         'Source contents, effects and rendered pixels are unverified.'],
        'references': ['docs/premiere.md', 'src/schemaxis/adaptors/premiere/readiness.json'],
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'operations': {
            'sequenceContract': {
                'purpose': 'Observe exact native sequence/clip ticks and source identities against declared contiguous cut ranges; no native mutation.',
                'keywords': ['contiguous cut', 'ordered clips', 'source ranges', 'read-only inspection'],
                'groups': ['inspection'], 'related': ['sequenceLayout'],
                'semantics': ['Experimental integration; native acceptance remains pending.',
                              'One unmuted contiguous video track and empty audio tracks.',
                              'Two matching bounded observations are not an atomic snapshot.',
                              'Source contents, effects and rendered pixels are not checked.']},
            'sequenceLayout': {
                'purpose': 'Check a complete named track layout with gaps and overlays; require editorial coverage across selected video tracks and frame ranges.',
                'keywords': ['track layout', 'coverage gate', 'gap audit', 'multitrack inspection', 'overlay intersection', 'read-only inspection'],
                'groups': ['inspection'], 'related': ['sequenceContract'],
                'semantics': ['Complete ordered named video tracks, including empty tracks; extra native tracks fail.',
                              'Every track is unmuted, every clip enabled; at most eight tracks, 128 clips and 600 frames.',
                              'Coverage counts exact half-open editorial intervals, not visible rendered footage.',
                              'Experimental integration; native acceptance remains pending.']}}}
