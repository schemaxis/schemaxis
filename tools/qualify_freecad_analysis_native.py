"""Independent public-API edit, second solve and fresh reopen qualification."""
import copy
import json
import math
import os
import subprocess
from pathlib import Path
import FreeCAD as App
from femtools.ccxtools import FemToolsCcx
from schemaxis.artifacts import atomic_json
from schemaxis.adaptors.freecad.analysis_native import observed
from schemaxis.adaptors.freecad.analysis_saved import safe_to_open,payloads,verify as verify_saved
from schemaxis.adaptors.freecad.analysis_results import verify as verify_results
from schemaxis.adaptors.freecad.analysis_boundary import materialise


def main(root,stage):
    root=Path(root);baseline=root/'axial-quadratic';original=json.loads((baseline/'plan.json').read_text())
    if stage=='edit1':source=baseline/'analysis.FCStd';prepared=copy.deepcopy(original);prepared['material']['youngModulusMPa']=140000;prepared['loads'][0]['forceN']=[200,0,0];expected=1
    elif stage=='edit2':source=root/'edit1/analysis.FCStd';prepared=json.loads((root/'edit1/plan.json').read_text());prepared['material']['youngModulusMPa']=70000;prepared['loads'][0]['forceN']=[50,0,0];expected=.5
    else:
        prepared=json.loads((root/'edit2/plan.json').read_text());safe_to_open(prepared,root/'edit2/analysis.FCStd');doc=App.openDocument(str(root/'edit2/analysis.FCStd'));doc.recompute()
        r=observed(doc,prepared);summary=verify_results(prepared,root/'edit2',r)
        verify_saved(prepared,root/'edit2/analysis.FCStd',r,json.loads((root/'edit2/payloads.json').read_text()))
        assert math.isclose(summary['maxDisplacementMM'],.5*100*20/(16*70000),rel_tol=3e-5)
        atomic_json(root/'edit-reopened.json',{'verified':True,'pid':os.getpid(),'analysis':summary});App.closeDocument(doc.Name);return
    # This only opens the adaptor's bounded generated document after its proxy,
    # external-reference and extension whitelist has passed on the host.
    safe_to_open(prepared,source);doc=App.openDocument(str(source));directory=root/stage;directory.mkdir()
    atomic_json(directory/'plan.json',prepared);mat=doc.getObject('Material');m=dict(mat.Material);m['YoungsModulus']=str(prepared['material']['youngModulusMPa'])+' MPa';mat.Material=m
    doc.getObject('Load0').Force=str(prepared['loads'][0]['forceN'][0])+' N'
    tool=FemToolsCcx(analysis=doc.getObject('Analysis'),solver=doc.getObject('Solver'));tool.purge_results()
    for name in ('ccx_dat_file',):
        if doc.getObject(name):doc.removeObject(name)
    doc.recompute();tool.update_objects();tool.setup_working_dir(str(directory));assert not tool.check_prerequisites();tool.write_inp_file()
    from schemaxis.adaptors.freecad.faces import native_inventory
    deck=directory/'Mesh.inp';materialise(prepared,deck,native_inventory(doc.getObject('Solid').Shape));text=deck.read_text();at=text.upper().rfind('*END STEP');deck.write_text(text[:at]+'*NODE PRINT,NSET=Nall\nU,RF\n'+text[at:])
    engine=Path(App.getHomePath())/'bin/ccx';process=subprocess.run([str(engine),'-i','Mesh'],cwd=str(directory),capture_output=True,text=True,timeout=180,env=dict(os.environ,OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='1'))
    (directory/'solver.stdout.log').write_text(process.stdout);assert process.returncode==0,process.stdout
    tool.load_results();doc.recompute();record=observed(doc,prepared);summary=verify_results(prepared,directory,record)
    assert math.isclose(summary['maxDisplacementMM'],expected*100*20/(16*70000),rel_tol=3e-5)
    for obj in doc.Objects:obj.Visibility=obj.Name in ('Solid','Pipeline_CCX_Results')
    doc.saveAs(str(directory/'analysis.FCStd'))
    from schemaxis.adaptors.freecad.gui_state import persist
    persist(directory/'analysis.FCStd',{o.Name:bool(o.Visibility) for o in doc.Objects})
    atomic_json(directory/'payloads.json',payloads(directory/'analysis.FCStd'));atomic_json(directory/'edited.json',{'verified':True,'pid':os.getpid(),'analysis':summary});App.closeDocument(doc.Name)
