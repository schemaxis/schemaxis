"""Scientific scope and recovery stay local to the CalculiX adaptor."""
from schemaxis.core.faults import Fault,SchemaxisError

def fault(code,message,location='$',**observed):
    recovery = {'INVALID_BEAM':'Use a rectangular slender beam in the declared SI domain; keep deformation and strain small.',
                'NUMERICAL_ACCEPTANCE_FAILED':'Inspect retained mesh/refinement and beam-theory errors; revise section, material or mesh within the supported domain and rerun a fresh attempt.',
                'PERFORMANCE_NOT_MET':'Inspect measured requirement margins; increase stiffness/section or reduce the force, or revise the stated serviceability limit, then rerun a fresh attempt.',
                'VERIFICATION_FAILED':'Preserve failed native evidence and rerun the unchanged authored beam in a fresh directory.'}
    raise SchemaxisError(Fault(code,message,location,'pipeline',observed=observed,
        recovery=recovery.get(code,'Correct the located input or select a usable absolute CalculiX 2.23 executable; rerun a fresh attempt.')))
