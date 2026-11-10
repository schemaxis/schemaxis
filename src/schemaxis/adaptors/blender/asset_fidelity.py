"""Typed comparison of reconstructed native asset fidelity.

Native floating-point settings may round during replay. Integers and custom
metadata have exact types and values; they are not geometric tolerances.
"""
from .settings import matching as native_matching

VERSION = 'schemaxis.blender.asset-fidelity/2'


def check_version(fidelity, location):
    """Old colliding-tree receipts need a trusted-input rebuild, never a relabel."""
    from schemaxis.errors import fail, SchemaxisError, Fault
    version = fidelity.get('version') if isinstance(fidelity, dict) else None
    if version == 'schemaxis.blender.asset-fidelity/1':
        raise SchemaxisError(Fault('RERUN_REQUIRED',
            'asset proof predates owner-qualified material-tree fidelity',
            location, 'pipeline', recovery=(
                'Preserve this run. Rerun its authored intent in a NEW output directory '
                'from the retained trusted original asset inputs; explicitly adopt those '
                'original bytes if needed. Do not resnapshot the submitted project or '
                'relabel its stored fidelity witness. Raw original assets remain reusable.')))
    if version != VERSION:
        fail('VERIFICATION_FAILED', 'asset fidelity version is absent or unrecognised', location)


def matching(actual, expected, *, exact=False):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            matching(actual[key], value, exact=exact or key in ('customProperties','attributeInputs'))
            for key, value in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            matching(a, b, exact=exact) for a, b in zip(actual, expected))
    if type(expected) is float and not exact:
        return native_matching(actual, expected)
    return actual == expected
