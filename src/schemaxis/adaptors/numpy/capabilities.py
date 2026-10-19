"""Curated discovery for unit-aware principal component analysis."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'NumPy',
            'purpose': 'Explain correlated multi-channel numeric measurements with independently verified principal components, '
                       'explained variance and a bounded reconstruction in the channels\' own units.',
            'keywords': ['NumPy', 'principal component analysis', 'PCA', 'multichannel measurements', 'dimensionality reduction']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['Isolated Python with exactly NumPy 2.5.4 linked to OpenBLAS 0.3.34 on POSIX; the host never imports NumPy.',
                         'Bounded ASCII numeric CSV whose header equals the declared optional row key and channels.'],
        'references': ['docs/numpy.md', 'src/schemaxis/adaptors/numpy/readiness.json'],
        'operations': {'principalComponents': {
            'purpose': 'Find the dominant correlated patterns in captured multi-channel measurements: centred, explicitly scaled '
                       'principal components with labelled loadings, scores, explained variance and a verified reconstruction.',
            'keywords': ['principal component analysis', 'PCA', 'principal components', 'eigenvalues', 'explained variance',
                         'scree', 'loadings', 'scores', 'dimensionality reduction', 'correlated channels', 'sensor array',
                         'common mode', 'reconstruction error', 'covariance', 'correlation matrix', 'standardise', 'SVD'],
            'semantics': ['Mean centring and the n-1 variance denominator are fixed; scaling is none (one shared unit), standardise or declared per channel.',
                          'Repeated or near-repeated eigenvalues never publish an arbitrary per-component basis; subspace output publishes the projector.',
                          'Requirements are decided by the independent host verifier as met, unmet or indeterminate; only met results are accepted deliverables.'],
            'examples': [{'reference': 'examples/schemaxis/numpy-sensors.json', 'purpose': 'Two dominant patterns in four analytic millivolt channels.'},
                         {'reference': 'examples/schemaxis/numpy-sensors-standardised.json', 'purpose': 'Correlation PCA with a retained-subspace projector.'},
                         {'reference': 'examples/schemaxis/numpy-pressure-drift.json', 'purpose': 'Synthetic drifting pressure transducers near the offset limit.'}]}}
    }
