"""Godot faults use the shared transport envelope."""
from schemaxis.core.faults import SchemaxisError, Fault


def fault(code, message, location='$', recovery='Correct the declared input and retry in a fresh output directory.'):
    raise SchemaxisError(Fault(code, message, location, 'godot', recovery=recovery))
