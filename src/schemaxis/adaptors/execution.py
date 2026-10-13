"""Execution capability checks delegated to the selected adaptor."""
from schemaxis.errors import fail
from .registry import route_hook


def validate_execution(document, ranks):
    if ranks == 1: return
    hook = route_hook(document, 'validateExecution', legacy=True)
    if hook is None: fail('UNSUPPORTED_EXECUTION', 'this adaptor has no MPI execution mode', version=document.get('version'))
    hook(document)
