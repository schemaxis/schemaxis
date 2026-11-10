"""One bounded native/STEP precision request for typed helical outputs."""
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .gauss_green import Budget, EvaluationLimit, MeasurementDeadline, Unresolved
from .mass_native import measure_levels

METHOD = 'schemaxis.freecad.gauss-green/2'
BOUNDARY_METHOD = 'explicit-completed-boundary/1'


def _measure(shape, budget):
    return measure_levels(shape, budget=budget, boundary_method=BOUNDARY_METHOD)


def _request(action):
    """Share the fixed request budget, including named intermediate solids."""
    try:
        budget=Budget(maximum=4_000_000,seconds=remaining_timeout(240),
                      checkpoint=lambda:remaining_timeout(240))
        return action(budget)
    except EvaluationLimit as error:
        fail('RESOURCE_LIMIT','Helix precision measurement exhausted its fixed evaluation budget',
             'model.step',reason=str(error))
    except MeasurementDeadline as error:
        fail('RUNNER_TIMED_OUT','Helix precision measurement exhausted its deadline',
             'model.step',reason=str(error))
    except Unresolved as error:
        fail('VERIFICATION_FAILED','Helix precision measurement could not resolve',
             'model.step',reason=str(error))


def _named(shapes, budget, native=None, native_record=None, output_identity=None):
    if len(shapes)>32:
        raise EvaluationLimit('named solid inventory exceeds the fixed request bound')
    result={}
    for identity,shape in shapes.items():
        budget.check()
        # Reuse only the exact same native occurrence and placement. An
        # intermediate feature or differently placed instance is measured.
        if (identity==output_identity and native is not None
                and shape.isEqual(native)):
            result[identity]=native_record
        else:
            result[identity]=_measure(shape,budget)
    return result


def named(shapes):
    """Live named measurements have the same bounded instrument and faults."""
    return _request(lambda budget:_named(shapes,budget))


def pair(native, step, *, measurement_shapes=None, output_identity=None):
    import FreeCAD as App
    import Part

    def measure(budget):
        first=_measure(native,budget)
        second=_measure(step,budget)
        result={'method':METHOD,'runtime':{'freecad':App.Version(),'occ':Part.OCC_VERSION},
                'maximumEvaluations':4_000_000,'native':first,'step':second}
        if measurement_shapes is not None:
            result['measurements']=_named(measurement_shapes,budget,native,first,output_identity)
        result['evaluations']=budget.calls
        return result
    return _request(measure)
