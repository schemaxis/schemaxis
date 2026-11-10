"""Isolated FreeCAD FEM build/solve/reopen workers for reviewed static solid intent."""
import json
import math
import os
import subprocess
from pathlib import Path
import FreeCAD as App
import Part
import ObjectsFem
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.errors import fail
from schemaxis.core.faults import SchemaxisError
from .faces import native_inventory,resolve
from .analysis import FILES,verify_observation


def shape_facts(shape):
    box=shape.optimalBoundingBox(False,False)
    return {'valid':bool(shape.isValid()),'solids':len(shape.Solids),'volume':float(shape.Volume),
        'bounds':[box.XMin,box.XMax,box.YMin,box.YMax,box.ZMin,box.ZMax],
        'centreOfMass':list(shape.Solids[0].CenterOfMass) if len(shape.Solids)==1 else None}


def references(obj):return [[o.Name,list(sub)] for o,sub in obj.References]


def observed(doc,prepared):
    analysis=doc.getObject('Analysis');mat=doc.getObject('Material');mesh=doc.getObject('Mesh');solver=doc.getObject('Solver');source=doc.getObject('Solid')
    result=doc.getObject('CCX_Results')
    if result is None:fail('SOLVER_FAILED','FreeCAD has no imported mechanical result')
    nodes=list(result.NodeNumbers)
    fields={'displacements':{str(n):list(v) for n,v in zip(nodes,result.DisplacementVectors)},
        'stresses':{str(n):[float(getattr(result,p)[i]) for p in ['NodeStressXX','NodeStressYY','NodeStressZZ','NodeStressXY','NodeStressYZ','NodeStressXZ']] for i,n in enumerate(nodes)}}
    record={'objects':{o.Name:o.TypeId for o in doc.Objects},'analysisGroup':[o.Name for o in analysis.Group],
        'material':dict(mat.Material),'mesh':{'shape':mesh.Shape.Name,'sizeMM':float(mesh.CharacteristicLengthMax.Value),'order':mesh.ElementOrder,'dimension':mesh.ElementDimension,
            'straightMidsides':bool(mesh.SecondOrderLinear),'nodes':int(mesh.FemMesh.NodeCount),'elements':int(mesh.FemMesh.VolumeCount)},
        'meshNodes':{str(n):list(v) for n,v in mesh.FemMesh.Nodes.items()},'meshCells':{str(n):list(mesh.FemMesh.getElementNodes(n)) for n in mesh.FemMesh.Volumes},
        'supports':{},'loads':{},'solver':{'analysis':solver.AnalysisType,'geometry':solver.GeometricalNonlinearity,'material':solver.MaterialNonlinearity,'space':solver.ModelSpace,'split':bool(solver.SplitInputWriter)},
        'faces':native_inventory(source.Shape),'shape':shape_facts(source.Shape),'result':fields}
    for index,support in enumerate(prepared['supports']):
        obj=doc.getObject('Support'+str(index));record['supports'][obj.Name]={'id':obj.Label,'references':references(obj),'displacementMM':[None if getattr(obj,a+'Free') else float(getattr(obj,a+'Displacement').Value) for a in 'xyz'],'suppressed':bool(obj.Suppressed)}
        if any(getattr(obj,'has'+a+'Formula') for a in 'XYZ') or obj.EnableAmplitude:fail('VERIFICATION_FAILED','Support has undeclared time/formula dependence')
    for index,load in enumerate(prepared['loads']):
        obj=doc.getObject('Load'+str(index));r={'id':obj.Label,'references':references(obj),'kind':load['kind']}
        if load['kind']=='force':
            vector=list(obj.DirectionVector);size=float(obj.Force.getValueAs('N'))*(-1 if obj.Reversed else 1)
            r['forceN']=[v*size for v in vector]
            if obj.Direction is not None:fail('VERIFICATION_FAILED','Force uses an undeclared native direction link')
        else:r['pressureMPa']=float(obj.Pressure.getValueAs('MPa'))*(-1 if obj.Reversed else 1)
        if obj.Suppressed or obj.EnableAmplitude:fail('VERIFICATION_FAILED','Load has undeclared suppression or time dependence')
        record['loads'][obj.Name]=r
    if any(o.ExpressionEngine for o in doc.Objects):fail('VERIFICATION_FAILED','FEM objects have undeclared expressions')
    verify_observation(prepared,record);return record


def build(directory,prepared):
    directory=Path(directory);doc=App.newDocument('SchemaxisAnalysis')
    source=doc.addObject('Part::Feature','Solid');shape=Part.Shape();shape.read(str(directory/('source.brep' if prepared['source']['format']=='FCStd' else 'source.step')));source.Shape=shape
    facts=shape_facts(shape)
    from .adaptor import close
    if not facts['valid'] or facts['solids']!=1 or any(not close(facts[k],prepared['source'][v]) for k,v in [('volume','volume'),('bounds','bounds'),('centreOfMass','centreOfMass')]):fail('INVALID_GEOMETRY','Captured solid differs from declared independent geometry expectations')
    analysis=ObjectsFem.makeAnalysis(doc,'Analysis');mat=ObjectsFem.makeMaterialSolid(doc,'Material');material=prepared['material']
    mat.Material={'Name':material['name'],'YoungsModulus':str(material['youngModulusMPa'])+' MPa','PoissonRatio':str(material['poissonRatio']),'Density':str(material['densityKgPerM3'])+' kg/m^3'};analysis.addObject(mat)
    mesh=ObjectsFem.makeMeshGmsh(doc,'Mesh');mesh.Shape=source;mesh.CharacteristicLengthMax=prepared['mesh']['sizeMM'];mesh.CharacteristicLengthMin=prepared['mesh']['sizeMM']/2
    mesh.ElementOrder='2nd' if prepared['mesh']['order']==2 else '1st';mesh.ElementDimension='3D';mesh.SecondOrderLinear=True;mesh.MeshSizeFromCurvature=24;mesh.Algorithm3D='Delaunay';analysis.addObject(mesh)
    inventory=native_inventory(shape)
    for index,support in enumerate(prepared['supports']):
        face=resolve(support['face'],inventory,support['id']);obj=ObjectsFem.makeConstraintDisplacement(doc,'Support'+str(index));obj.Label=support['id'];obj.References=[(source,['Face'+str(face['index'])])]
        for a,value in zip('xyz',support['displacementMM']):
            setattr(obj,a+'Free',value is None)
            if value is not None:setattr(obj,a+'Displacement',value)
        analysis.addObject(obj)
    for index,load in enumerate(prepared['loads']):
        face=resolve(load['face'],inventory,load['id']);obj=(ObjectsFem.makeConstraintForce if load['kind']=='force' else ObjectsFem.makeConstraintPressure)(doc,'Load'+str(index));obj.Label=load['id'];obj.References=[(source,['Face'+str(face['index'])])]
        if load['kind']=='force':
            magnitude=math.hypot(*load['forceN']);obj.Force=str(magnitude)+' N';obj.DirectionVector=App.Vector(*[v/magnitude for v in load['forceN']]);obj.Reversed=False
        else:obj.Pressure=str(abs(load['pressureMPa']))+' MPa';obj.Reversed=load['pressureMPa']<0
        analysis.addObject(obj)
    solver=ObjectsFem.makeSolverCalculiXCcxTools(doc,'Solver');analysis.addObject(solver);solver.AnalysisType='static';solver.GeometricalNonlinearity='linear';solver.MaterialNonlinearity='linear';solver.ModelSpace='3D';solver.SplitInputWriter=False;doc.recompute()
    bundle=Path(App.getHomePath())/'bin';gmsh=bundle/'gmsh';ccx=bundle/'ccx'
    if not gmsh.is_file() or not ccx.is_file():fail('INTERPRETER_NOT_FOUND','This route needs the FreeCAD installation bundled Gmsh and CalculiX executables')
    from femmesh.gmshtools import GmshTools
    mesher=GmshTools(mesh);mesher.update_mesh_data();mesher.get_tmp_file_paths(str(directory),True);mesher.gmsh_bin=str(gmsh);mesher.write_gmsh_input_files()
    error=mesher.run_gmsh_with_geo()
    if error:fail('MESH_FAILED','Native FEM Gmsh generation failed',detail=str(error))
    mesher.read_and_set_new_mesh();doc.recompute()
    if not 1<=mesh.FemMesh.NodeCount<=prepared['mesh']['maxNodes'] or not 1<=mesh.FemMesh.VolumeCount<=prepared['mesh']['maxElements']:fail('RESOURCE_BUDGET_EXCEEDED','Generated FEM mesh exceeds its node/element budget')
    from femtools.ccxtools import FemToolsCcx
    tool=FemToolsCcx(analysis=analysis,solver=solver);tool.update_objects();tool.setup_working_dir(str(directory));errors=tool.check_prerequisites()
    if errors:fail('INVALID_ANALYSIS','Native FEM analysis prerequisites failed',detail=str(errors))
    tool.write_inp_file();deck=Path(tool.inp_file_name)
    if deck.name!='Mesh.inp' or deck.parent!=directory:fail('VERIFICATION_FAILED','Native FEM writer changed the owned input-deck path')
    from .analysis_boundary import materialise
    materialise(prepared,deck,inventory)
    text=deck.read_text();at=text.upper().rfind('*END STEP')
    if at<0:fail('VERIFICATION_FAILED','Native static deck has no final step boundary')
    # Request actual nodal displacement/force output for independent equilibrium
    # and strain-energy verification. The record uses the writer's own Nall set.
    text=text[:at]+'*NODE PRINT,NSET=Nall\nU,RF\n'+text[at:];deck.write_text(text)
    env=dict(os.environ,OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    # CalculiX limits the -i stem to 127 characters. The owned working directory
    # already selects the deck; passing its basename also supports deep workflow
    # attempt paths without changing any model or solver setting.
    try:process=subprocess.run([str(ccx),'-i','Mesh'],cwd=str(directory),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=180,env=env)
    except subprocess.TimeoutExpired:fail('TIMEOUT','CalculiX exceeded its native solve bound')
    (directory/'solver.stdout.log').write_text(process.stdout);(directory/'solver.stderr.log').write_text(process.stderr)
    if process.returncode!=0 or not (directory/'Mesh.frd').is_file() or not (directory/'Mesh.dat').is_file():fail('SOLVER_FAILED','CalculiX static solve failed',exitCode=process.returncode)
    if not __import__('re').search(r'CalculiX Version 2\.23\b',process.stdout):fail('UNSUPPORTED_RUNTIME','The native FEM bridge is qualified for bundled CalculiX2.23')
    tool.load_results();doc.recompute();record=observed(doc,prepared)
    from .analysis_results import verify as verify_results
    summary=verify_results(prepared,directory,record);atomic_json(directory/'analysis.json',summary)
    for obj in doc.Objects:obj.Visibility=obj.Name in ('Solid','Pipeline_CCX_Results')
    doc.saveAs(str(directory/'analysis.FCStd'))
    from .gui_state import persist
    persist(directory/'analysis.FCStd',{o.Name:bool(o.Visibility) for o in doc.Objects})
    atomic_json(directory/'build.json',{'definition':prepared,'pid':os.getpid(),'runtime':App.Version(),'observed':record,
        'savedPayloads':__import__('schemaxis.adaptors.freecad.analysis_saved',fromlist=['payloads']).payloads(directory/'analysis.FCStd'),
        'engines':{'gmsh':str(gmsh),'calculix':str(ccx),'exitCode':process.returncode}});App.closeDocument(doc.Name)


def reopen(directory,prepared):
    from .analysis_saved import safe_to_open
    directory=Path(directory);safe_to_open(prepared,directory/'analysis.FCStd')
    doc=App.openDocument(str(directory/'analysis.FCStd'));doc.recompute();record=observed(doc,prepared)
    artifacts=[]
    for filename,kind in FILES:
        item={'file':str(directory/filename),'kind':kind,'sha256':file_digest(directory/filename),'units':'mm' if kind=='cadScene' else 'per-field'}
        if kind=='cadScene':item['spatial']={'state':'known','frame':'stored-CAD-shape','units':'mm','boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax'],'axisOrder':['x','y','z'],'bounds':prepared['source']['bounds'],'coordinateRepresentation':'world coordinates stored in geometry'}
        else:item['spatial']={'state':'notApplicable'}
        artifacts.append(item)
    receipt={'definition':prepared,'pid':os.getpid(),'runtime':App.Version(),'observed':record,'artifacts':artifacts}
    atomic_json(directory/'reopen.json',receipt);atomic_json(directory/'verification.json',receipt);App.closeDocument(doc.Name)


def main(directory,stage):
    directory=Path(directory)
    try:
        if App.Version()[:2]!=['1','1']:fail('UNSUPPORTED_RUNTIME','Native FEM bridge requires FreeCAD1.1.x')
        prepared=json.loads((directory/'plan.json').read_text());(build if stage=='build' else reopen)(directory,prepared)
    except Exception as error:
        fault=error.fault.to_dict() if isinstance(error,SchemaxisError) else {'code':'NATIVE_EXECUTION_FAILED','message':str(error),'location':'$','phase':'native','observed':{'exceptionType':type(error).__name__}}
        atomic_json(directory/'native-fault.json',fault);raise
