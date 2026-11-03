# Copyright (C) 2026 David L F Gaden
"""Application-independent data traits and evidence-qualified cost assessment.

Compatibility and cost are separate. Missing traits never count as support, and
cost hints without a stated basis never become a fast/slow claim. No conversion
is performed by assessment.
"""
from .errors import fail


def assess(requirements, traits, cost=None):
    """Requirements map trait names to acceptable values; traits are observations."""
    missing, incompatible = [], []
    for key, accepted in requirements.items():
        if not isinstance(accepted, list) or not accepted:
            fail('INVALID_DATA_CONTRACT', 'trait requirements need nonempty alternatives', key)
        actual = traits.get(key, 'unknown')
        if actual == 'unknown' or actual is None:
            missing.append(key)
        elif actual not in accepted:
            incompatible.append({'trait':key,'actual':actual,'accepted':accepted})
    status = 'unsupported' if incompatible else 'unknown' if missing else 'supported'
    performance = {'rating':'unknown','basis':'no applicable cost evidence'}
    if cost and cost.get('rating') in ('fast','slow'):
        if not cost.get('basis') or not cost.get('conditions'):
            fail('INVALID_COST_CONTRACT', 'cost ratings require evidence and applicability conditions')
        condition = assess(cost['conditions'], traits)
        if condition['compatibility'] == 'supported':
            performance = {k:cost[k] for k in ('rating','basis','conditions')}
    return {'compatibility':status,'missingTraits':missing,'incompatibleTraits':incompatible,
            'performance':performance,'conversion':'none inserted'}


def __getattr__(name):
    # Retained public import compatibility, never used by framework code.
    if name == 'paraview_traits':
        from .adaptors.paraview.traits import paraview_traits
        return paraview_traits
    raise AttributeError(name)
