"""Run with pvbatch create_reader_fixtures.py OUTPUT_DIRECTORY."""
from paraview import simple as p
from vtkmodules.vtkCommonDataModel import vtkStructuredGrid,vtkRectilinearGrid
from vtkmodules.vtkCommonCore import vtkPoints,vtkDoubleArray
from vtkmodules.vtkIOXML import vtkXMLStructuredGridWriter,vtkXMLRectilinearGridWriter
from pathlib import Path
import sys, json
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True, exist_ok=True)
s=p.Sphere();w=p.Wavelet();u=p.Tetrahedralize(Input=w);g=p.GroupDatasets(Input=[s,w])
for source,name in [(s,'surface.stl'),(s,'surface.ply'),(w,'image.vti'),(u,'mesh.vtu'),(g,'blocks.vtm')]:
    p.SaveData(str(root/name),proxy=source)
points=vtkPoints()
for z in range(2):
 for y in range(2):
  for x in range(2): points.InsertNextPoint(x,y,z)
sgrid=vtkStructuredGrid();sgrid.SetDimensions(2,2,2);sgrid.SetPoints(points)
rgrid=vtkRectilinearGrid();rgrid.SetDimensions(2,2,2)
for method in ['SetXCoordinates','SetYCoordinates','SetZCoordinates']:
 a=vtkDoubleArray();a.InsertNextValue(0);a.InsertNextValue(1);getattr(rgrid,method)(a)
for data,name,kind in [(sgrid,'structured.vts',vtkXMLStructuredGridWriter),(rgrid,'rectilinear.vtr',vtkXMLRectilinearGridWriter)]:
 writer=kind();writer.SetFileName(str(root/name));writer.SetInputData(data);assert writer.Write()

pairs=[('readSTL','surface.stl'),('readPLY','surface.ply'),('readImageData','image.vti'),('readUnstructuredGrid','mesh.vtu'),('readMultiBlock','blocks.vtm'),('readStructuredGrid','structured.vts'),('readRectilinearGrid','rectilinear.vtr')]
nodes=[{'id':name,'filter':name,'options':{'files':[str(root/file)]}} for name,file in pairs]
(root/'readers.json').write_text(json.dumps({'version':'schemaxis/1','nodes':nodes,'scenes':[{'id':'readers','geometry':[n['id'] for n in nodes]}]},indent=2)+'\n')
