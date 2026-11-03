# Copyright (C) 2026 David L F Gaden
"""Saved feedback-loop settings, without claiming native coupling execution.

These settings describe point-coupling convergence, not an adaptor's internal
solver tolerance. Convergence must use the raw feedback residual, before any
relaxation. The eventual executor must also establish units and variable scales;
small relaxed steps alone cannot demonstrate a converged coupled solution.
"""

from copy import deepcopy
import math

from .core.faults import Fault, SchemaxisError


_COMMON_DEFAULTS = {
    'maxIterations': 50,
    'absoluteTolerance': 1e-6,
    'relativeTolerance': 1e-4,
}
_POINT_REQUIREMENTS = [
    'Explicit feedback variables with compatible units and declared scales.',
    'Repeatable participant evaluations; stateful trials need a common restored start.',
    'Convergence measured from raw feedback residuals before relaxation.',
    'A qualified feedback executor, which is not yet available.',
]
_CATALOGUE = [
    {
        'id': 'fixed-point',
        'label': 'Fixed point',
        'kind': 'point-coupling',
        'configurable': True,
        'status': 'configuration-only',
        'executionAvailable': False,
        'reason': 'Save bounded fixed-point settings for this loop; native feedback execution is not yet available.',
        'requires': _POINT_REQUIREMENTS,
        'convergence': 'raw-residual',
        'defaults': {'algorithm': 'fixed-point', **_COMMON_DEFAULTS},
    },
    {
        'id': 'constant-relaxation',
        'label': 'Constant relaxation',
        'kind': 'point-coupling',
        'configurable': True,
        'status': 'configuration-only',
        'executionAvailable': False,
        'reason': 'Save a constant relaxation factor for this loop; native feedback execution is not yet available.',
        'requires': _POINT_REQUIREMENTS,
        'convergence': 'raw-residual',
        'defaults': {'algorithm': 'constant-relaxation', **_COMMON_DEFAULTS, 'relaxation': 0.5},
    },
    {
        'id': 'aitken',
        'label': 'Aitken relaxation',
        'kind': 'point-coupling',
        'configurable': False,
        'status': 'unavailable',
        'executionAvailable': False,
        'reason': 'Adaptive relaxation and its numerical safeguards are not implemented.',
        'requires': [*_POINT_REQUIREMENTS,
                     'Residual history, scaling, and safeguarded adaptive relaxation.'],
    },
    {
        'id': 'quasi-newton',
        'label': 'Quasi-Newton coupling',
        'kind': 'point-coupling',
        'configurable': False,
        'status': 'unavailable',
        'executionAvailable': False,
        'reason': 'Coupling acceleration and its history/rank safeguards are not implemented.',
        'requires': [*_POINT_REQUIREMENTS,
                     'Consistent residual vectors and safeguarded iteration history.'],
    },
    {
        'id': 'step-doubling',
        'label': 'Step doubling',
        'kind': 'time-step-control',
        'configurable': False,
        'status': 'unavailable',
        'executionAvailable': False,
        'reason': 'Time-step error control is not a generic algebraic-loop solver; participant restore/advance support is not supplied.',
        'requires': [
            'Time- or parameter-stepping participants with a declared integration order.',
            'Restore all participants to the identical trial start for one full step and two half steps.',
            'Scaled error estimates, bounded rejection, event handling, and accepted-state publication.',
        ],
    },
    {
        'id': 'stsc',
        'label': 'Source Term Stabilisation Coupling (STSC)',
        'kind': 'source-coupling',
        'configurable': False,
        'status': 'unavailable',
        'executionAvailable': False,
        'reason': 'Qualified participant source-contribution channels and their discretisation contracts are not supplied.',
        'requires': [
            'Isolated participant contributions and explicit source-term read/write channels.',
            'Participant-owned source conversion, units, sign conventions, and discretisation.',
            'Compatible boundary mappings, restored iteration state, convergence and invariant checks.',
        ],
    },
]


def catalogue():
    """Return independent JSON records; configurable does not mean executable."""
    return [deepcopy(record) for record in _CATALOGUE]


def _fault(message, location, *, code='INVALID_FEEDBACK_CONFIG', recovery=None):
    raise SchemaxisError(Fault(
        code, message, location, 'validation',
        recovery=recovery or 'Correct the loop settings and save the configuration again.'))


def _number(value, location, *, positive=False):
    # bool is an int in Python, but is never an authored numeric setting.
    if type(value) not in (int, float):
        _fault('expected a finite number', location)
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (positive and value == 0):
        _fault('expected a positive finite number' if positive
               else 'expected a nonnegative finite number', location)


def validate_config(config, location='$'):
    """Validate saved settings and return a fresh JSON object.

    Graph ownership and the existence of a feedback loop are checked by the
    workflow-design layer. This function never makes a cyclic workflow runnable.
    """
    if not isinstance(config, dict):
        _fault('feedback configuration must be an object', location)
    algorithm = config.get('algorithm')
    if not isinstance(algorithm, str):
        _fault('algorithm must be a catalogue identifier', location + '.algorithm')
    record = next((item for item in _CATALOGUE if item['id'] == algorithm), None)
    if record is None:
        _fault('unknown feedback algorithm', location + '.algorithm',
               recovery='Choose a configurable algorithm from the feedback catalogue.')
    if not record['configurable']:
        _fault(record['reason'], location + '.algorithm',
               code='FEEDBACK_ALGORITHM_UNAVAILABLE',
               recovery='Choose fixed point or constant relaxation to save settings; native loop execution remains unavailable.')

    required = {'algorithm', 'maxIterations', 'absoluteTolerance', 'relativeTolerance'}
    if algorithm == 'constant-relaxation':
        required.add('relaxation')
    if set(config) - required:
        _fault('unsupported feedback configuration fields', location,
               recovery='Use only the fields declared for the selected feedback algorithm.')
    missing = sorted(required - set(config))
    if missing:
        _fault('missing feedback configuration field', location + '.' + missing[0])

    count = config['maxIterations']
    if type(count) is not int or not 1 <= count <= 1000:
        _fault('maxIterations must be an integer from 1 to 1000', location + '.maxIterations')
    _number(config['absoluteTolerance'], location + '.absoluteTolerance', positive=True)
    _number(config['relativeTolerance'], location + '.relativeTolerance')
    if algorithm == 'constant-relaxation':
        _number(config['relaxation'], location + '.relaxation', positive=True)
        if config['relaxation'] > 1:
            _fault('relaxation must be greater than zero and at most one', location + '.relaxation')
    return deepcopy(config)
