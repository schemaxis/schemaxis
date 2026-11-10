"""Trusted Elmer SIF/mesh mappings and independent bounded ASCII readers."""
import math
import re
import xml.etree.ElementTree as ET
from .physics import mesh,check


def sources(p):
    x,elements=mesh(p);n=len(x)
    files={
        'mesh/mesh.header':f'{n} {len(elements)} 2\n2\n101 2\n202 {len(elements)}\n',
        'mesh/mesh.nodes':'\n'.join(f'{i+1} -1 {v:.17g} 0 0' for i,v in enumerate(x))+'\n',
        'mesh/mesh.elements':'\n'.join(f'{i+1} {m+1} 202 {i+1} {i+2}' for i,m in enumerate(elements))+'\n',
        'mesh/mesh.boundary':f'1 1 1 0 101 1\n2 2 {len(elements)} 0 101 {n}\n'}
    common='''Header
  CHECK KEYWORDS Warn
  Mesh DB "." "mesh"
  Results Directory ""
End
Simulation
  Max Output Level = 5
  Coordinate System = "Cartesian 1D"
  Simulation Type = "Steady State"
  Steady State Max Iterations = 1
  Output Intervals = 1
'''
    bodies=[]
    for i,layer in enumerate(p['layers'],1):
        bodies.append(f'''Body {i}
  Target Bodies(1) = {i}
  Equation = 1
  Material = {i}
  Body Force = {i}
End
Material {i}
  Heat Conductivity = {layer['conductivity_W_mK']:.17g}
  Density = 1
  Heat Capacity = 1
End
Body Force {i}
  Heat Source = {layer['heatGeneration_W_m3']:.17g}
End
''')
    boundaries=[]
    for i,side in enumerate(('left','right'),1):
        b=p[side]
        if b['kind']=='value':value=f'Temperature = {b["value"]:.17g}'
        elif b['kind']=='flux':value=f'Heat Flux = {-b["value"]:.17g}\n  Heat Flux BC = True'
        else:value=f'Heat Transfer Coefficient = {b["coefficient"]:.17g}\n  External Temperature = {b["ambient"]:.17g}\n  Heat Flux BC = True'
        boundaries.append(f'Boundary Condition {i}\n  Target Boundaries(1) = {i}\n  {value}\nEnd\n')
    heat='''Equation 1
  Active Solvers(2) = 1 2
End
Solver 1
  Equation = "Heat Equation"
  Procedure = "HeatSolve" "HeatSolver"
  Variable = Temperature
  Variable DOFs = 1
  Optimize Bandwidth = False
  Linear System Solver = Direct
  Linear System Direct Method = UMFPack
  Nonlinear System Max Iterations = 1
  Nonlinear System Convergence Tolerance = 1e-10
  Steady State Convergence Tolerance = 1e-10
'''
    def output(prefix):
        return f'''Solver 2
  Exec Solver = After Simulation
  Equation = ResultOutput
  Procedure = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "{prefix}"
  Vtu Format = True
  Save Geometry Ids = True
  Binary Output = False
End
'''
    files['model.sif']=common+'  Output File = "thermal.result"\nEnd\n'+heat+'End\n'+output('native')+''.join(bodies+boundaries)
    # Declare the Temperature variable but never solve it: fresh-process restart
    # is the only source of the reopened field. Retain all input mappings.
    files['reopen.sif']=common+'  Restart File = "thermal.result"\n  Restart Position = 0\n  Restart Before Initial Conditions = True\n  Initialize Dirichlet Conditions = False\nEnd\n'+heat+'  Exec Solver = Never\nEnd\n'+output('reopened')+''.join(bodies+boundaries)
    return files


def read_vtu(path,p):
    try:root=ET.fromstring(path.read_bytes())
    except ET.ParseError as error:check(False,'invalid native VTU: '+str(error))
    pieces=root.findall('./UnstructuredGrid/Piece');check(len(pieces)==1,'expected one native mesh piece')
    piece=pieces[0];x,elements=mesh(p);n=len(x)
    check(piece.get('NumberOfPoints')==str(n) and piece.get('NumberOfCells')==str(n-1),'native VTU mesh counts differ')
    def array(parent,name=None):
        arrays=piece.findall(parent+'/DataArray');items=[a for a in arrays if name is None or a.get('Name')==name]
        check(len(items)==1 and items[0].get('format','ascii').lower()=='ascii','missing/ambiguous/non-ASCII native VTU array: '+str(name))
        values=[float(v) for v in (items[0].text or '').split()];check(all(math.isfinite(v) for v in values),'nonfinite native VTU values');return values
    coordinates=array('Points');check(len(coordinates)==3*n,'native coordinate width differs')
    check(all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12) for a,b in zip(coordinates,[float(f'{v:.7e}') for point in x for v in (point,0,0)])),'native coordinates differ')
    check(array('Cells','connectivity')==[v for i in range(n-1) for v in (i,i+1)],'native line connectivity differs')
    check(array('CellData','GeometryIds')==[m+1 for m in elements],'native VTU material membership differs')
    check(array('Cells','offsets')==list(range(2,2*n,2)) and array('Cells','types')==[3]*(n-1),'native cell types/offsets differ')
    values=array('PointData','temperature');check(len(values)==n,'native temperature count differs');return values


def read_result(path,p):
    """Parse the documented ASCII Elmer restart field, separate from VTU export."""
    lines=path.read_text().splitlines();n=len(mesh(p)[0])
    # This bounded mapping disables bandwidth reordering, so solver and node
    # indices must be identical. Elmer WritePerm writes node/solver pairs;
    # WriteReal emits values by node order (ModelDescription.F90 SaveResult).
    check(bool(lines) and lines[0].strip()=='ASCII 3' and sum(line.startswith('Time:') for line in lines)==1,'expected one ASCII3 steady result')
    check(any(re.fullmatch(r'\s*Total DOFs:\s*1\s*',line) for line in lines),'expected one native scalar temperature variable')
    check(any(re.fullmatch(r'\s*Number Of Nodes:\s*'+str(n)+r'\s*',line) for line in lines),'native restart header node count differs')
    matches=[i for i,line in enumerate(lines) if line.strip()=='temperature']
    check(len(matches)==1,'native restart requires exactly one Temperature field')
    start=matches[0]+1
    while start<len(lines) and not lines[start].strip():start+=1
    check(lines[start].strip().startswith('Perm:'),'native restart Temperature permutation absent')
    counts=[int(v) for v in lines[start].split(':')[1].split()];check(counts==[n,n],'native restart node count differs')
    pairs=[[int(v) for v in line.split()] for line in lines[start+1:start+1+n]]
    check(all(len(v)==2 for v in pairs) and [v[0] for v in pairs]==list(range(1,n+1)) and [v[1] for v in pairs]==list(range(1,n+1)),'native restart permutation differs')
    data=[float(v) for line in lines[start+1+n:start+1+2*n] for v in line.split()]
    check(len(data)==n and len(lines)==start+1+2*n and all(math.isfinite(v) for v in data),'native restart field count differs')
    return data
