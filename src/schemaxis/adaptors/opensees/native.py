"""Trusted isolated worker. Input selects physical records, never commands."""
import json
import importlib.metadata
import math
import os
from pathlib import Path
import sys


class NativeUnavailable(Exception): pass
class UnsupportedRuntime(Exception): pass


def main(directory,stage):
    try:
        import openseespy.opensees as ops
        package_version=importlib.metadata.version('openseespy')
    except (ImportError,importlib.metadata.PackageNotFoundError) as error:
        raise NativeUnavailable('install stable OpenSeesPy3.8.0.0 in the configured isolated interpreter: '+str(error)) from error
    if ops.version()!='3.8.0' or package_version!='3.8.0.0': raise UnsupportedRuntime('requires OpenSees3.8.0 / OpenSeesPy3.8.0.0; observed '+ops.version()+' / '+package_version)
    p=json.loads((directory/'model.json').read_text()); nodes=p['nodes']; index={n['id']:i+1 for i,n in enumerate(nodes)}
    ops.wipe(); ops.model('basic','-ndm',2,'-ndf',2)
    for i,n in enumerate(nodes,1): ops.node(i,n['x_m'],n['y_m']); ops.fix(i,*map(int,n['fixed']))
    for i,m in enumerate(p['members'],1):
        ops.uniaxialMaterial('Elastic',i,m['youngsModulus_Pa']);ops.element('Truss',i,index[m['a']],index[m['b']],m['area_m2'],i)
    if ops.getNodeTags()!=list(range(1,len(nodes)+1)) or ops.getEleTags()!=list(range(1,len(p['members'])+1)): raise ValueError('native tag readback differs')
    coords=[ops.nodeCoord(i) for i in range(1,len(nodes)+1)]
    fixed=[ops.getFixedDOFs(i) for i in range(1,len(nodes)+1)]
    if fixed!=[[j+1 for j,v in enumerate(n['fixed']) if v] for n in nodes]: raise ValueError('native support readback differs')
    connects=[ops.eleNodes(i) for i in range(1,len(p['members'])+1)]
    if coords!=[[n['x_m'],n['y_m']] for n in nodes] or connects!=[[index[m['a']],index[m['b']]] for m in p['members']]: raise ValueError('native geometry readback differs')
    ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
    for load in p['loads']: ops.load(index[load['node']],*load['force_N'])
    ops.constraints('Plain');ops.numberer('Plain');ops.system('FullGeneral');ops.test('NormDispIncr',1e-12,5);ops.algorithm('Linear');ops.integrator('LoadControl',1);ops.analysis('Static')
    if ops.analyze(1)!=0 or ops.getTime()!=1: raise ValueError('linear static step failed')
    ops.reactions(); results={'nodes':[],'members':[]}
    for i,n in enumerate(nodes,1): results['nodes'].append({'id':n['id'],'displacement_m':ops.nodeDisp(i),'reaction_N':ops.nodeReaction(i)})
    material=[]
    for i,m in enumerate(p['members'],1):
        a,b=(nodes[index[m[k]]-1] for k in ('a','b')); length=math.hypot(b['x_m']-a['x_m'],b['y_m']-a['y_m'])
        force=ops.eleResponse(i,'axialForce')[0]; stress=ops.eleResponse(i,'material','stress')[0];strain=ops.eleResponse(i,'material','strain')[0]; tangent=ops.eleResponse(i,'material','tangent')[0]
        if not math.isclose(tangent,m['youngsModulus_Pa'],rel_tol=1e-12) or not math.isclose(force,stress*m['area_m2'],rel_tol=1e-10,abs_tol=1e-8): raise ValueError('native material/area readback differs')
        area=ops.basicStiffness(i)[0]*length/tangent
        if not math.isclose(area,m['area_m2'],rel_tol=1e-12): raise ValueError('native axial stiffness area readback differs')
        material.append({'youngsModulus_Pa':tangent,'area_m2':area})
        results['members'].append({'id':m['id'],'length_m':length,'force_N':force,'stress_Pa':stress,'strain':strain})
    record={'stage':stage,'pid':os.getpid(),'runtime':{'name':'OpenSeesPy','version':ops.version(),'packageVersion':package_version,'executable':sys.executable},'model':p,'coordinates':coords,'connections':connects,'materials':material,'fixedDOFs':fixed,'results':results}
    (directory/(stage+'.json')).write_text(json.dumps(record,indent=2,allow_nan=False)+'\n');ops.wipe()


if __name__=='__main__':
    directory=Path(sys.argv[1])
    try: main(directory,sys.argv[2])
    except Exception as error:
        code={NativeUnavailable:'NATIVE_UNAVAILABLE',UnsupportedRuntime:'UNSUPPORTED_RUNTIME'}.get(type(error),'NATIVE_EXECUTION_FAILED')
        (directory/'native-fault.json').write_text(json.dumps({'code':code,'message':str(error)[:2000]}))
        raise
