# Copyright (C) 2026 David L F Gaden
"""Meshing intent and a bounded coarser-to-finer acceptance policy."""
import copy
import json
import math
from pathlib import Path

from schemaxis import feedback
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from . import mesh

ARGUMENTS = {
    'maxIterations': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 4},
    'reductionFactor': {'type': 'number', 'minimum': .1, 'maximum': .95, 'default': .7},
    'minimumSize': {'type': 'number', 'minimum': .001, 'maximum': 100000, 'default': .1},
    'maxTetrahedra': {'type': 'integer', 'minimum': 1, 'maximum': mesh.MAX_CELLS, 'default': 50000},
    'requirements': {'type': 'object', 'required': True, 'properties': {
        'maximumEdgeLength': {'type': 'number', 'minimum': .001, 'maximum': 100000},
        'minimumMeanRatio': {'type': 'number', 'minimum': .000001, 'maximum': 1},
        'maximumVolumeRelativeError': {'type': 'number', 'minimum': .00000001, 'maximum': .02},
        'boundaryMaximumEdgeLength': {'type': 'array', 'minItems': 1, 'maxItems': 13, 'items': {
            'type': 'object', 'properties': {
                'boundary': {'type': 'string', 'minLength': 1, 'maxLength': 64, 'required': True},
                'maximum': {'type': 'number', 'minimum': .001, 'maximum': 100000, 'required': True}}}}}}}


def schema():
    from schemaxis.schema import arguments_schema
    result = arguments_schema(ARGUMENTS)
    result['properties']['requirements']['minProperties'] = 1
    return result


def prepare(raw, prepared):
    keys(raw, tuple(ARGUMENTS), '$.refinement')
    result = validate_arguments(ARGUMENTS, raw, location='$.refinement')
    if not result['requirements']:
        fail('INVALID_STUDY', 'declare at least one mesh acceptance requirement', '$.refinement.requirements')
    if result['minimumSize'] > prepared['nodes'][1]['options']['size']:
        fail('INVALID_STUDY', 'minimumSize must not exceed the initial mesh size', '$.refinement.minimumSize')
    settings = prepared['nodes'][1]['options']
    names = {settings['boundaryName']} | {group['name'] for group in settings['faceGroups']}
    seen = set()
    for target in result['requirements'].get('boundaryMaximumEdgeLength', []):
        if target['boundary'] not in names or target['boundary'] in seen:
            fail('INVALID_SELECTION', 'boundary requirements need distinct declared boundary names')
        seen.add(target['boundary'])
    return result


class Policy:
    def __init__(self, document):
        from .adaptor import _native_plan
        prepared = _native_plan(document)
        self.settings = prepared['refinement']
        self.limit = self.settings['maxIterations']
        self.base = copy.deepcopy(document)
        self.base.pop('refinement')
        self.initial_size = prepared['nodes'][1]['options']['size']
        self.initial_boundaries = prepared['nodes'][1]['options']['nearBoundaries']

    def describe(self):
        return {'name': 'gmsh.geometric-refinement/1', **self.settings,
                'initialSize': self.initial_size, 'sizeUnits': 'mm',
                'boundarySizing': 'scale boundary sizes with global size, with a 0.001 mm floor; keep transition distances fixed',
                'limitations': ['smaller target size does not guarantee improved element shape',
                                'first acceptable tested mesh; not a minimum-cell optimisation',
                                'mesh requirements do not establish solver convergence',
                                'maxTetrahedra limits acceptable candidates; native work has its own hard cap']}

    def propose(self, history):
        size = self.initial_size if not history else history[-1]['document']['nodes'][1]['options']['size']*self.settings['reductionFactor']
        if history and history[-1]['document']['nodes'][1]['options']['size'] <= self.settings['minimumSize']:
            return None
        size = max(size, self.settings['minimumSize'])
        candidate = copy.deepcopy(self.base)
        candidate['nodes'][1].setdefault('options', {})['size'] = size
        candidate['nodes'][1]['options']['nearBoundaries'] = [
            {**rule, 'size': max(.001, rule['size']*size/self.initial_size)} for rule in self.initial_boundaries]
        return candidate

    def judge(self, candidate, observation, history):
        if history and observation['capturedSource'] != history[0]['observation']['capturedSource']:
            fail('INPUT_CHANGED', 'CAD source changed between refinement attempts')
        checks = []
        def check(name, observed, relation, requested, units):
            checks.append({'requirement': name, 'observed': observed, 'relation': relation,
                           'requested': requested, 'units': units,
                           'passed': observed <= requested if relation == '<=' else observed >= requested})
        check('maxTetrahedra', observation['tetrahedra'], '<=', self.settings['maxTetrahedra'], 'cells')
        for name, requested in sorted(self.settings['requirements'].items()):
            if name == 'maximumEdgeLength':
                check(name, observation['quality']['maximumEdgeLength']['maximum'], '<=', requested, 'mm')
            elif name == 'minimumMeanRatio':
                check(name, observation['quality']['meanRatio']['minimum'], '>=', requested, 'dimensionless')
            elif name == 'maximumVolumeRelativeError':
                check(name, observation['volumeRelativeError'], '<=', requested, 'dimensionless')
            elif name == 'boundaryMaximumEdgeLength':
                boundaries = {b['name']: b for b in observation['quality']['boundaries']}
                for target in requested:
                    check('boundaryMaximumEdgeLength:'+target['boundary'],
                          boundaries[target['boundary']]['maximumEdgeLength']['maximum'], '<=', target['maximum'], 'mm')
        accepted = all(c['passed'] for c in checks)
        stop = 'cell_budget_exceeded' if not checks[0]['passed'] else None
        # Stop before proposing a candidate outside the native work estimate.
        # This is an explicit resource decision, not an assertion about convergence.
        if not accepted and stop is None and 'cadBounds' in observation:
            size = max(self.settings['minimumSize'], candidate['nodes'][1]['options']['size']*self.settings['reductionFactor'])
            minimum = min([size]+[max(.001, r['size']*size/self.initial_size) for r in self.initial_boundaries])
            bounds = observation['cadBounds']
            estimate = 6*math.prod((bounds[i+3]-bounds[i])/minimum+1 for i in range(3))
            if estimate > mesh.MAX_CELLS: stop = 'work_estimate_limit'
        return {'accepted': accepted, 'checks': checks, 'stop': stop}


def observe(directory):
    result = json.loads((directory/'mesh-summary.json').read_text())
    result['capturedSource'] = json.loads((directory/'sources.json').read_text())
    return result


def require_accepted(result, directory):
    if not result['accepted']:
        fail('STUDY_REQUIREMENTS_NOT_MET', 'no tested mesh satisfied all requirements; inspect study-summary.json',
             str(directory), reason=result['reason'], attempts=result['attempts'])
    return result


def run(document, directory, *, executable, timeout):
    from .adaptor import _native_run, _native_verify
    result = feedback.run(document, directory, Policy(document),
                          lambda d, p, **options: _native_run(d, p, executable=executable, **options),
                          _native_verify, observe, timeout=timeout)
    require_accepted(result, directory)
    return {**result, 'status': 'succeeded'}


def verify(directory, *, require_acceptance=True):
    from .adaptor import _native_verify
    directory = Path(directory).absolute()
    document = json.loads((directory/'authored.json').read_text())
    result = feedback.verify(directory, document, Policy(document), _native_verify, observe)
    return require_accepted(result, directory) if require_acceptance else result
