# Copyright (C) 2026 David L F Gaden
"""Preserve structured native faults across an application subprocess boundary."""
from pathlib import Path
from schemaxis.core.faults import SchemaxisError, Fault
from .artifacts import atomic_json


def execute_guarded(function, directory):
    try:
        return function(directory)
    except Exception as error:
        fault = error.fault if isinstance(error, SchemaxisError) else Fault(
            'NATIVE_EXECUTION_FAILED', str(error) or type(error).__name__, '$', 'native',
            observed={'exceptionType': type(error).__name__})
        atomic_json(Path(directory) / 'native-fault.json', fault.to_dict())
        raise
