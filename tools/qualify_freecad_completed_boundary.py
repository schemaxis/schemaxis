#!/usr/bin/env python3
"""Focused empirical completed-boundary qualification using real product APIs.

Run under the programme's bounded launcher. Default controls construct literal
solids and a known STEP projection incoherence; they do not rerun the historical
75-case aggregate or change its FALSE result. Optional trusted, programme-created
BREP/STEP fixtures exercise pair admission, or the actual shared-budget pair with
--full-pair. No submitted FCStd is opened by this tool.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.core.runners import Interpreter

MODULES = ('mass_native.py','mass_boundary_native.py','mass_boundary_admission.py',
           'mass_completion_native.py','mass_ruled_native.py','gauss_green.py',
           'pcurve_native.py','helix_precision_native.py','line_endpoint_jumps.py',
           'conic_phase.py','conic_lens.py')

# Original far-UV construction and literal semidisk oracle were qualified in
# the independent P1 controls. This version deliberately classifies only its
# STEP projection as an expected coherence refusal; the old aggregate remains
# unchanged. No inspect/exec/AST transformation of production functions occurs.
NATIVE = r'''
import math,time,traceback,json,hashlib
from pathlib import Path
import FreeCAD as App,Part
from schemaxis.adaptors.freecad.gauss_green import Budget,Unresolved
from schemaxis.adaptors.freecad.mass_native import prepare,measure_levels
from schemaxis.adaptors.freecad.mass_boundary_admission import coarse_winding
from schemaxis.adaptors.freecad.helix_precision_native import pair
out=Path(CONFIG['output']);method='explicit-completed-boundary/1'
report={'verified':False,'recipe':'completed-boundary-qualification/1',
        'runtime':{'freecad':App.Version(),'occ':Part.OCC_VERSION},
        'source':CONFIG['source'],'cases':{},'failures':{},
        'scope':'named controls only; no certified numerical bound or whole-family qualification',
        'historical75AggregateReclassified':False}
def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
def case(name,fn):
    start=time.monotonic()
    try:report['cases'][name]={'result':fn(),'seconds':time.monotonic()-start}
    except Exception:report['failures'][name]=traceback.format_exc()
    save()
def refused(fn,reason):
    try:fn()
    except Unresolved as error:
        accepted=(reason,)if isinstance(reason,str)else reason
        assert any(item in str(error)for item in accepted),(accepted,str(error))
        return {'classification':'expected-refusal','reason':str(error)}
    raise AssertionError('expected substantive refusal: '+reason)
def literal(shape,expected,fans=0):
    result=measure_levels(shape,budget=Budget(),boundary_method=method)
    fine=result['fine'];actual=[fine['area'],fine['signedVolume'],*fine['centre']]
    assert all(math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-6)for a,b in zip(actual,expected)),(actual,expected)
    assert fine['completion']['counts']['collapsedFans']>=fans
    return {'actual':actual,'literal':expected,'evaluations':result['evaluations'],
            'completionCounts':fine['completion']['counts'],'admission':result['boundaryAdmission'],
            'coarseWinding':result['coarseWinding']}
case('box',lambda:literal(Part.makeBox(3,4,5),[94,60,1.5,2,2.5]))
case('cylinder',lambda:literal(Part.makeCylinder(3,5),[48*math.pi,45*math.pi,0,0,2.5]))
case('sphere-two-poles',lambda:literal(Part.makeSphere(3),[36*math.pi,36*math.pi,0,0,0],2))
case('cone-one-pole',lambda:literal(Part.makeCone(3,0,4),[24*math.pi,12*math.pi,0,0,1],1))

def conic_meridian(angle,required_kind):
    # r=3t, z=5t^2: integrate circular sections directly, independently of
    # the product's surface evaluator and boundary quadrature. A quarter
    # additionally has two radial faces of area10 and x/y moments18.
    curve=Part.BezierCurve()
    curve.setPoles([App.Vector(),App.Vector(1.5,0,0),App.Vector(3,0,5)])
    profile=Part.Face(Part.Wire([curve.toShape(),
        Part.makeLine(App.Vector(3,0,5),App.Vector(0,0,5)),
        Part.makeLine(App.Vector(0,0,5),App.Vector())]))
    fresh=profile.revolve(App.Vector(),App.Vector(0,0,1),angle)
    assert fresh.isValid() and len(fresh.Solids)==1
    # The qualified period/tangent cases concern stored BREP decimals, as in
    # saved native publications. A fresh binary64 2*pi endpoint need not have
    # the same period residual. Keep this phase explicit in the evidence.
    path=out/('conic-'+required_kind+'.brep');fresh.exportBrep(str(path))
    shape=Part.Shape();shape.read(str(path))
    assert shape.isValid() and len(shape.Solids)==1
    side=math.pi*(109**1.5-27)/50
    expected=([9*math.pi+side,45*math.pi/2,0,0,10/3] if angle==360 else
              [(9*math.pi+side)/4+20,45*math.pi/8,3.2/math.pi,3.2/math.pi,10/3])
    result=measure_levels(shape,budget=Budget(),boundary_method=method)
    fine=result['fine'];actual=[fine['area'],fine['signedVolume'],*fine['centre']]
    limits=[max(1e-6,abs(value)*1e-7)/10 for value in expected]
    assert all(abs(a-e)<=limit for a,e,limit in zip(actual,expected,limits)),(actual,expected)
    admission=result['boundaryAdmission'];lenses=admission['declaredConicLenses']
    assert lenses and all(lens['kind']==required_kind and lens['bound'] is False for lens in lenses)
    assert admission['idealLawClosureCertified'] is False
    for level in ('coarse','fine'):
        proxy=result[level]['conicLensProxy']
        assert proxy['bound'] is False and len(proxy['records'])==len(lenses)
        assert all(len(record['samples'])==9 and record['bound'] is False for record in proxy['records'])
        assert all(math.isfinite(value) and value>=0 for value in proxy['totals'])
    return {'actual':actual,'literal':expected,'limits':limits,
            'fixture':{'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                       'phase':'owned construction exported to BREP and read afresh'},
            'evaluations':result['evaluations'],'admission':admission,
            'coarseLensDiagnostic':result['coarse']['conicLensProxy'],
            'fineLensDiagnostic':fine['conicLensProxy'],
            'scope':'finite native availability and sampled diagnostics; endpoint joins and 3D rungs remain unmodelled'}
case('conic-surplus-turn-paraboloid',lambda:conic_meridian(360,'one-surplus-turn'))
case('conic-terminal-tangent-quarter',lambda:conic_meridian(90,'exact-terminal-tangent'))
case('reversed-sphere',lambda:refused(lambda:measure_levels(Part.makeSphere(3).reversed(),boundary_method=method),'positive signed volume'))
case('reversed-cone',lambda:refused(lambda:measure_levels(Part.makeCone(3,0,4).reversed(),boundary_method=method),'positive signed volume'))
case('unknown-method',lambda:refused(lambda:prepare(Part.makeBox(1,1,1),Budget(),boundary_method='unreviewed/1'),'unreviewed boundary'))
for radius in (.03,3.,3000.):
    def scaled_mesh(radius=radius):
        shape=Part.makeSphere(radius);before=shape.exportBrepToString()
        row=coarse_winding(shape,4*math.pi*radius**3/3,4*math.pi*radius**2,Budget())
        assert shape.exportBrepToString()==before
        return row
    case('coarse-mesh-scale-'+str(radius),scaled_mesh)

def far_uv():
    origin=10000.;xs=(0,.185,.685,1);ys=(0,.305,.805,1)
    surface=Part.BSplineSurface()
    surface.buildFromPolesMultsKnots([[App.Vector(x,y,0)for y in ys]for x in xs],
        [3,1,3],[3,1,3],[origin,origin+.37,origin+1],[origin,origin+.61,origin+1],False,False,2,2)
    radius=.4;c=origin+.5
    circle=Part.Geom2d.Circle2d(App.Base.Vector2d(c,c),radius)
    arc=Part.Geom2d.ArcOfCircle2d(circle,math.pi/4,5*math.pi/4)
    a,b=5*math.pi/4,math.pi/4
    line=Part.Geom2d.Line2dSegment(App.Base.Vector2d(c+radius*math.cos(a),c+radius*math.sin(a)),
                                  App.Base.Vector2d(c+radius*math.cos(b),c+radius*math.sin(b)))
    native=Part.Face(surface,Part.Wire([arc.toShape(surface),line.toShape(surface)])).extrude(App.Vector(0,0,3))
    assert native.isValid() and len(native.Solids)==1
    native.exportStep(str(out/'far-uv.step'));step=Part.Shape();step.read(str(out/'far-uv.step'))
    assert step.isValid() and len(step.Solids)==1
    delta=4*radius/(3*math.pi)*math.sqrt(.5)
    expected=[math.pi*radius**2+3*(math.pi*radius+2*radius),1.5*math.pi*radius**2,.5-delta,.5+delta,1.5]
    return native,step,expected
try:
    far,farstep,expected=far_uv()
    case('far-uv-native-literal',lambda:literal(far,expected))
    case('far-uv-step-expected-coherence-refusal',lambda:refused(
        lambda:measure_levels(farstep,boundary_method=method),'trace pair exceeds summed native edge tolerances'))
except Exception:report['failures']['far-uv-fixture']=traceback.format_exc();save()

if CONFIG['native']:
    native=Part.Shape();native.read(CONFIG['native'])
    step=Part.Shape();step.read(CONFIG['step'])
    admission_budget=Budget()
    def admission_one(shape):
        prepared=prepare(shape,admission_budget,boundary_method=method)
        state=prepared['completionState']
        return {'classification':'admission-only','ledger':state['admission'],
                'pairs':len(state['pairs']),'poles':len(state['poles']),
                'corners':len(state['corners']),'sharedEvaluations':admission_budget.calls}
    case('pair-native-admission-lite',lambda:admission_one(native))
    case('pair-step-admission-lite',lambda:admission_one(step))
    case('pair-strict-default-retained',lambda:refused(lambda:prepare(step,Budget()),
        ('pcurve and three-dimensional edge endpoints differ','oriented surface boundary chain')))
    if CONFIG['fullPair']:
        def full_pair():
            stock=Part.makeCylinder(10,148)
            result=pair(native,step,measurement_shapes={'coil':native,'stock':stock},output_identity='coil')
            assert result['measurements']['coil'] is result['native']
            fine=result['measurements']['stock']['fine'];values=[fine['area'],fine['signedVolume'],*fine['centre']]
            expected=[3160*math.pi,14800*math.pi,0,0,74]
            assert all(math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-6)for a,b in zip(values,expected))
            for level in ('coarse','fine'):
                for key in ('area','signedVolume','centre'):
                    a,b=result['native'][level][key],result['step'][level][key]
                    if not isinstance(a,list):a,b=[a],[b]
                    assert all(math.isclose(x,y,rel_tol=1e-7,abs_tol=1e-6)for x,y in zip(a,b))
            (out/'pair-precision.json').write_text(json.dumps(result,indent=2)+'\n')
            return {'evaluations':result['evaluations'],'maximumEvaluations':result['maximumEvaluations'],'literalStock':expected}
        case('actual-shared-budget-pair24-named-stock',full_pair)
report['verified']=not report['failures'];save()
'''


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad',required=True)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--native-brep',type=Path,help='trusted programme-generated 24-turn original BREP')
    parser.add_argument('--step',type=Path,help='corresponding trusted original STEP')
    parser.add_argument('--full-pair',action='store_true')
    parser.add_argument('--expected-commit')
    args=parser.parse_args()
    if bool(args.native_brep)!=bool(args.step) or args.full_pair and not args.step:
        parser.error('use --native-brep and --step together; --full-pair requires both')
    inputs={}
    for name,path in (('native',args.native_brep),('step',args.step)):
        if path:
            if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=64*1024*1024:
                parser.error('trusted fixtures must be regular non-symlink files of at most 64MiB')
            inputs[name]={'file':str(path.resolve()),'sha256':digest(path)}
    head=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    if args.expected_commit and head!=args.expected_commit:parser.error('source commit differs from expected pin')
    hashes={name:digest(ROOT/'src/schemaxis/adaptors/freecad'/name)for name in MODULES}
    source={'commit':head,'sourceDigest':source_digest('freecad'),'moduleHashes':hashes,
            'qualifierSha256':digest(Path(__file__)),'inputs':inputs}
    directory=args.output_directory.absolute();directory.mkdir(parents=True,exist_ok=False)
    config={'output':str(directory),'source':source,'native':inputs.get('native',{}).get('file'),
            'step':inputs.get('step',{}).get('file'),'fullPair':args.full_pair}
    code='import sys\nsys.path.insert(0,'+repr(str(ROOT/'src'))+')\nCONFIG='+repr(config)+'\n'+NATIVE
    ast.parse(code,filename='completed-boundary-native.py')
    (directory/'launch.json').write_text(json.dumps({'config':config,'generatedCodeSha256':hashlib.sha256(code.encode()).hexdigest(),'astParsed':True},indent=2)+'\n')
    SubprocessRunner(Interpreter('freecad',args.freecad),directory,timeout=600)(code)
    if source_digest('freecad')!=source['sourceDigest'] or any(digest(ROOT/'src/schemaxis/adaptors/freecad'/n)!=v for n,v in hashes.items()):
        raise AssertionError('source changed during native qualification')
    if any(digest(Path(item['file']))!=item['sha256']for item in inputs.values()):
        raise AssertionError('trusted input changed during qualification')
    report=json.loads((directory/'report.json').read_text())
    for row in report['cases'].values():
        fixture=row.get('result',{}).get('fixture')
        if fixture:
            # Rehash the owned native fixture on the host as well. The worker
            # cannot replace source provenance with its own report field.
            name=fixture['file']
            if name not in ('conic-one-surplus-turn.brep','conic-exact-terminal-tangent.brep'):
                raise AssertionError('unexpected generated conic fixture name')
            path=directory/name
            if path.is_symlink() or not path.is_file() or digest(path)!=fixture['sha256']:
                raise AssertionError('generated conic fixture changed after qualification')
    print(json.dumps({'verified':report['verified'],'cases':list(report['cases']),'failures':report['failures']},indent=2))
    if not report['verified']:raise SystemExit(1)


if __name__=='__main__':main()
