# Copyright (C) 2026 David L F Gaden
"""Slicing scope and recovery stay local to the PrusaSlicer adaptor."""
from schemaxis.core.faults import Fault, SchemaxisError

RECOVERY = {
    'INVALID_PROFILE': 'Revise the located printer, material or print setting within the documented bounded FFF policy and replan.',
    'INVALID_RESOURCE': 'Give an absolute path to an existing regular .stl file within the 16 MiB budget.',
    'INVALID_MODEL': 'Export one closed, consistently oriented, non-degenerate triangle mesh; this adaptor does not repair meshes.',
    'INPUT_DIGEST_MISMATCH': 'The STL bytes differ from the declared sha256. Restore the intended file or deliberately update model.sha256.',
    'MODEL_OUT_OF_BOUNDS': 'Move placement.centre_mm, enlarge the declared bed/height if the machine really allows it, or scale the model before slicing.',
    'UNSUPPORTED_RUNTIME': 'Configure an absolute PrusaSlicer 2.9.6 console executable; other releases need separate acceptance.',
    'PERFORMANCE_NOT_MET': 'Inspect the native estimates and signed margins; change the profile or revise the declared limit, then run a fresh attempt.',
    'VERIFICATION_FAILED': 'Preserve the failed evidence and rerun the unchanged document in a fresh output directory.',
}


def fault(code, message, location='$', **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed,
        recovery=RECOVERY.get(code, 'Correct the located input or configure a usable absolute PrusaSlicer 2.9.6 executable; rerun a fresh attempt.')))
