"""Workflow provenance for procedural sprites."""

def reusableInputs(document):
    from .adaptor import plan
    plan(document)
    return {}
