# Copyright (C) 2026 David L F Gaden
"""Workflow input fingerprints include the actual bounded PNG source bytes."""

def reusableInputs(document):
    from .adaptor import plan
    from .inputs import inspect
    from schemaxis.core.faults import SchemaxisError
    prepared = plan(document)
    try:
        _, records = inspect(prepared)
        return {r['source']: r['sha256'] for r in records}
    except SchemaxisError:
        return None
