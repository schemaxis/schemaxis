"""Bind every independently parsed hole/cycle to typed geometric drilling intent."""
import math
from schemaxis.errors import fail

# The selected post emits eight places in mm/seconds. Use its prospective
# half-unit rounding bound (with one percent binary conversion allowance), not
# the looser six-place persisted Path precision or a model tolerance.
WORD_ROUNDING=.505e-8


def validate(prepared,replay):
    expected=[(spec,xy) for spec in prepared['operations'] if spec['operation']=='drill' for xy in spec['centres']]
    cycles=replay['cycles']
    if len(cycles)!=len(expected):fail('VERIFICATION_FAILED','Posted cycle count differs from every intended drill target')
    offset=0
    for spec in prepared['operations']:
        if spec['operation']!='drill':continue
        actual=cycles[offset:offset+len(spec['centres'])];offset+=len(actual);seen=set();wanted=spec['cycle']
        for cycle in actual:
            if cycle['tool']!=spec['tool'] or cycle['code']!=wanted['code'] or cycle['return']!=(98 if wanted['return']=='initial' else 99):
                fail('VERIFICATION_FAILED','Posted tool, cycle strategy or return mode differs from drilling intent',spec['id'])
            if not isinstance(cycle['centre'],list) or len(cycle['centre'])!=2:
                fail('VERIFICATION_FAILED','Posted drilling centre must have exactly two coordinates',spec['id'])
            matches=[i for i,xy in enumerate(spec['centres']) if all(abs(a-b)<=WORD_ROUNDING for a,b in zip(cycle['centre'],xy))]
            if len(matches)!=1 or matches[0] in seen:
                fail('VERIFICATION_FAILED','Posted drilling omitted, duplicated or substituted a source-bound target',spec['id'])
            seen.update(matches)
            for key,expected_value in (('bottom',spec['finish']),('retract',wanted['retract']),('dwell',wanted['dwell']),('peck',wanted['peck'])):
                value=cycle[key]
                if type(value) not in (int,float) or not math.isfinite(value) or abs(value-expected_value)>WORD_ROUNDING:
                    fail('VERIFICATION_FAILED','Posted drilling depth, retract, dwell or peck differs from typed intent',spec['id'],field=key)
    return cycles
