# Copyright (C) 2026 David L F Gaden
"""Numerical selection guidance; literal constraints remain in the declarations."""


def catalogue():
    operations = {
        'samples': ('Supply finite paired x/y observations without reading a file.',
                    'Vectors need equal lengths; ordering constraints depend on downstream operations.'),
        'readCSV': ('Read named numeric x/y columns from an existing CSV table.',
                    'Use an absolute file path. Missing values and nonnumeric cells are unsupported; units belong to the caller.'),
        'sequence': ('Generate evenly spaced inclusive coordinates with y equal to x.',
                     'Use for calibration and synthetic inputs; both endpoints are included.'),
        'wave': ('Generate a sampled sine or cosine signal.',
                 'Frequency is cycles per x unit, phase is radians, and x starts at start with the declared step.'),
        'scale': ('Apply factor times y plus offset while preserving x.',
                  'No implicit unit conversion; select factor and offset for the intended physical convention.'),
        'resample': ('Linearly interpolate onto a uniform grid between existing endpoints.',
                     'Requires strictly increasing x. Interpolation changes the sampling and does not preserve extrema between samples.'),
        'movingMean': ('Smooth y with an odd centred moving window.',
                       'The window shrinks at endpoints and must not exceed the number of samples.'),
        'derivative': ('Estimate dy/dx using secants, including nonuniform x.',
                       'Requires strictly increasing x; interior slopes use neighbouring samples and endpoint slopes are one-sided.'),
        'integral': ('Accumulate the trapezoidal integral of y over x.',
                     'Requires strictly increasing x; the first output equals initial and units are y-unit times x-unit.'),
        'linearFit': ('Fit a least-squares straight line and publish fitted y values.',
                      'Requires varying x. Slope, intercept and residual sum of squares are retained in native metadata.'),
        'fft': ('Find a one-sided amplitude spectrum of uniformly sampled real data.',
                'Requires 4–8192 samples in a power of two. x becomes frequency; amplitudes double interior bins but not DC or Nyquist.')}
    return {
        'groups': {'analysis': {'label': 'Numerical series', 'purpose': 'Prepare and analyse bounded real-valued samples.', 'domain': 'data-analysis'}},
        'requirements': ['No implicit physical-unit conversions or missing-value handling.',
                         'Host planning validates structure; execution also checks data-dependent sampling constraints.',
                         'Inspect CSV and statistics, then verify against independent host arithmetic.'],
        'references': ['docs/numerical-analysis.md', 'src/schemaxis/adaptors/octave/readiness.json',
                       'src/schemaxis/adaptors/octave/reference.py:evaluate'],
        'operations': {name: {'purpose': purpose, 'semantics': [semantics], 'groups': ['analysis'],
                             'examples': [{'purpose': 'Editable numerical calibration pipeline.',
                                           'reference': 'examples/schemaxis/analysis/octave-calibration.json'}]
                             if name in ('samples', 'sequence', 'wave', 'scale', 'resample', 'derivative', 'integral') else []}
                       for name, (purpose, semantics) in operations.items()}}
