"""Plan-selected numerical evidence, subordinate to full geometry authority."""
import math
from schemaxis.errors import fail
from .helix import active

VERSION = 'schemaxis.freecad.export/4'
METHOD = 'schemaxis.freecad.gauss-green/2'


def version(prepared):
    return VERSION if active(prepared) else 'schemaxis.freecad.export/2'


def exact(actual, expected):
    """Match the complete current trusted schema, finite values and exact types."""
    if type(actual) is not type(expected):return False
    if isinstance(expected,dict):
        return actual.keys()==expected.keys() and all(exact(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):
        return len(actual)==len(expected) and all(exact(a,b) for a,b in zip(actual,expected))
    if isinstance(expected,float) and not (math.isfinite(actual) and math.isfinite(expected)):return False
    return actual==expected


def verify(built, receipt, authority):
    """Submitted records never select the method or authorise their own values."""
    trusted=authority['exportEvidence']
    expected=trusted.get('precision')
    if (trusted.get('version')!=VERSION or not isinstance(expected,dict)
            or expected.get('method')!=METHOD or expected.get('maximumEvaluations')!=4_000_000
            or type(expected.get('evaluations')) is not int
            or not 0<expected['evaluations']<=4_000_000):
        fail('VERIFICATION_FAILED','Fresh trusted Helix precision evidence is incomplete')
    reopened=authority['reopenEvidence'];expected_reopen=reopened.get('precision')
    if (reopened.get('version')!=VERSION or not isinstance(expected_reopen,dict)
            or expected_reopen.get('method')!=METHOD or expected_reopen.get('maximumEvaluations')!=4_000_000
            or type(expected_reopen.get('evaluations')) is not int
            or not 0<expected_reopen['evaluations']<=4_000_000):
        fail('VERIFICATION_FAILED','Fresh trusted Helix reopen precision evidence is incomplete')
    for label,record,keys in (('build',built,{'version','shape','step','meshing','precision'}),
                              ('reopen',receipt,{'version','native','step','precision'})):
        if (not isinstance(record,dict) or set(record)!=keys or record.get('version')!=VERSION
                or not exact(record.get('precision'),expected if label=='build' else expected_reopen)):
            fail('VERIFICATION_FAILED','Helix evidence differs from current trusted measurement',label)
    # Independently resolved native and STEP levels must agree within exactly
    # the existing limits. Full native/STEP/STL payload binding proves identity;
    # scalar agreement alone is deliberately insufficient.
    from .saved_checks import _close
    for state in (expected,expected_reopen):
        for level in ('coarse','fine'):
            a,b=state['native'][level],state['step'][level]
            for key in ('area','signedVolume','centre'):
                if not _close(a[key],b[key]):
                    fail('VERIFICATION_FAILED','Native and STEP Helix precision metrics differ',
                         'model.step',level=level,measure=key)
                if not _close(state['native'][level][key],expected['native'][level][key]):
                    fail('VERIFICATION_FAILED','Helix precision geometry changed after reopening',level,measure=key)
    # Keep default native observations honest without comparing default STEP
    # mass to native mass (the kernel integration defect motivating v3).
    from .export_checks import native_facts
    expected_native=native_facts(trusted['shape'],'trusted native')
    expected_step=native_facts(trusted['step'],'trusted STEP')
    for actual,reference,label in ((built['shape'],expected_native,'build'),
                                    (receipt['native'],native_facts(reopened['native'],'trusted reopen'),'reopen'),
                                    (built['step'],expected_step,'build STEP'),
                                    (receipt['step'],native_facts(reopened['step'],'trusted reopened STEP'),'reopen STEP')):
        native_facts(actual,label)
        if set(actual)!=set(reference):fail('VERIFICATION_FAILED','Helix native fact membership differs',label)
        for key in reference:
            valid=(_close(actual[key],reference[key]) if key in
                   ('volume','area','curvedArea','bounds','centreOfMass') else exact(actual[key],reference[key]))
            if not valid:fail('VERIFICATION_FAILED','Helix native facts differ from trusted reconstruction',label,measure=key)
    return {'method':METHOD,'evaluations':{'build':expected['evaluations'],'reopen':expected_reopen['evaluations']},
            'geometryAuthority':'fresh native graph and full STEP/STL payloads'}
