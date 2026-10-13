"""Native reference and grading helpers; deliberately no Schemaxis imports.

Used by the benchmark coordinator, never installed as an adaptor. Inputs are
bounded by benchmark_workflows.py. Functions run in their owning native runtime.
"""
import json
from pathlib import Path
import sys


def cad(case, directory):
    import FreeCAD as app
    import Part
    doc = app.newDocument('Specimen')
    box = doc.addObject('Part::Box', 'Specimen')
    box.Length, box.Width, box.Height = case['length'], case['width'], case['height']
    doc.recompute()
    Part.export([box], str(directory/'part.step'))
    doc.saveAs(str(directory/'part.FCStd'))
    app.closeDocument(doc.Name)


def cad_info(case, directory):
    import FreeCAD as app
    import Part
    shape = Part.read(str(directory/'part.step'))
    doc = app.openDocument(str(directory/'part.FCStd'))
    shapes = [o.Shape for o in doc.Objects if hasattr(o, 'Shape') and not o.Shape.isNull()]
    result = {'stepVolume': shape.Volume, 'stepValid': shape.isValid(),
              'nativeVolumes': [s.Volume for s in shapes], 'objects': len(doc.Objects)}
    app.closeDocument(doc.Name)
    return result


def mesh(case, directory):
    import gmsh
    gmsh.initialize([], readConfigFiles=False)
    try:
        gmsh.model.add('specimen')
        gmsh.model.occ.importShapes(str(directory/'part.step'))
        gmsh.model.occ.synchronize()
        groups = {'fixed': [], 'loaded': [], 'outside': []}
        for _, tag in gmsh.model.getEntities(2):
            bounds = gmsh.model.getBoundingBox(2, tag)
            group = ('fixed' if abs(bounds[0])+abs(bounds[3]) < 1e-5 else
                     'loaded' if abs(bounds[0]-case['length'])+abs(bounds[3]-case['length']) < 1e-5 else 'outside')
            groups[group].append(tag)
        gmsh.model.addPhysicalGroup(3, [t for _, t in gmsh.model.getEntities(3)], 1)
        gmsh.model.setPhysicalName(3, 1, 'part')
        for name, tag in [('outside', 2), ('fixed', 3), ('loaded', 4)]:
            gmsh.model.addPhysicalGroup(2, groups[name], tag)
            gmsh.model.setPhysicalName(2, tag, name)
        gmsh.option.setNumber('Mesh.MeshSizeMin', case['meshSize'])
        gmsh.option.setNumber('Mesh.MeshSizeMax', case['meshSize'])
        gmsh.option.setNumber('Mesh.ElementOrder', 1)
        gmsh.option.setNumber('Mesh.MshFileVersion', 2.2)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(directory/'mesh.msh'))
    finally:
        gmsh.finalize()


def mesh_export(case, directory):
    # Read native MSH through a small, independent format parser, then create
    # VTK publications and let ParaView integrate the volume.
    from vtkmodules.vtkCommonCore import vtkPoints, vtkIntArray
    from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid
    from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridWriter
    lines = (directory/'mesh.msh').read_text().splitlines()
    i = lines.index('$Nodes'); records = [line.split() for line in lines[i+2:i+2+int(lines[i+1])]]
    points = vtkPoints(); points.SetDataTypeToDouble(); indices = {}
    for row in records:
        indices[int(row[0])] = points.InsertNextPoint(*map(float, row[1:]))
    i = lines.index('$Elements'); elements = [list(map(int, line.split())) for line in lines[i+2:i+2+int(lines[i+1])]]
    for name, kind, vtk_kind in [('volume', 4, 10), ('boundary', 2, 5)]:
        grid = vtkUnstructuredGrid(); grid.SetPoints(points)
        tags = vtkIntArray(); tags.SetName('physicalTag')
        for row in elements:
            if row[1] == kind:
                ids = [indices[n] for n in row[3+row[2]:]]
                grid.InsertNextCell(vtk_kind, len(ids), ids); tags.InsertNextValue(row[3])
        grid.GetCellData().AddArray(tags)
        writer = vtkXMLUnstructuredGridWriter(); writer.SetFileName(str(directory/(name+'.vtu')))
        writer.SetInputData(grid); writer.SetDataModeToAscii(); assert writer.Write()
    mesh_inspect(case, directory)


def mesh_inspect(case, directory):
    from paraview import simple as p
    reader = p.XMLUnstructuredGridReader(FileName=[str(directory/'volume.vtu')])
    integral = p.IntegrateVariables(Input=reader)
    p.SaveData(str(directory/'inspection.csv'), proxy=integral)


def cfd(case, directory):
    from paraview import simple as p
    reader = p.OpenFOAMReader(FileName=case['file']); reader.CaseType = case.get('caseType','Reconstructed Case')
    reader.SkipZeroTime = 0; reader.MeshRegions = ['internalMesh']; reader.CellArrays = ['U', 'p']
    merged = p.MergeBlocks(Input=reader)
    cut = p.Slice(Input=merged); cut.SliceType.Normal = [1, 0, 0]
    for ti, time in enumerate(case['times']):
        for fi, fraction in enumerate(case['fractions']):
            cut.SliceType.Origin = [case.get('xmin',0)+fraction*case['length'], 0, 0]
            cut.UpdatePipeline(time=time)
            p.SaveData(str(directory/f'slice-{ti}-{fi}.vtp'), proxy=cut)


def case_info(case, directory):
    from paraview import simple as p, servermanager
    reader=p.OpenFOAMReader(FileName=case['file']);reader.CaseType=case.get('caseType','Reconstructed Case')
    reader.SkipZeroTime=0;reader.MeshRegions=['internalMesh'];reader.CellArrays=['U','p'];reader.UpdatePipelineInformation()
    times=list(reader.TimestepValues)
    merged=p.MergeBlocks(Input=reader);merged.UpdatePipeline(time=case.get('time',times[-1]))
    data=servermanager.Fetch(merged)
    return {'times':times,'bounds':list(data.GetBounds()),'cells':data.GetNumberOfCells(),
            'fields':[data.GetCellData().GetArrayName(i) for i in range(data.GetCellData().GetNumberOfArrays())]}


def vtk_info(case, directory):
    from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader, vtkXMLPolyDataReader
    from vtkmodules.vtkFiltersVerdict import vtkCellSizeFilter
    result = {}
    names = (['volume.vtu', 'boundary.vtu'] if case['family'] == 'mesh' else
             [f'slice-{ti}-{fi}.vtp' for ti in range(len(case['times'])) for fi in range(len(case['fractions']))])
    for name in names:
        reader = vtkXMLPolyDataReader() if name.endswith('.vtp') else vtkXMLUnstructuredGridReader()
        reader.SetFileName(str(directory/name)); reader.Update(); data = reader.GetOutput()
        assert data.GetNumberOfCells() > 0, 'empty publication '+name
        size = vtkCellSizeFilter(); size.SetInputData(data); size.Update()
        measured = size.GetOutput(); fields = {}
        for key in ('U', 'p', 'physicalTag'):
            array = data.GetCellData().GetArray(key)
            if array:
                fields[key] = [list(array.GetTuple(i)) for i in range(array.GetNumberOfTuples())]
        groups = {}
        tags = data.GetCellData().GetArray('physicalTag')
        areas = measured.GetCellData().GetArray('Area')
        for i in range(data.GetNumberOfCells()):
            if tags:
                tag = str(int(tags.GetTuple1(i)))
                row = groups.setdefault(tag, {'area': 0, 'points': []})
                row['area'] += areas.GetTuple1(i)
                cell = data.GetCell(i)
                row['points'].extend([list(data.GetPoint(cell.GetPointId(j))) for j in range(cell.GetNumberOfPoints())])
        volumes = measured.GetCellData().GetArray('Volume')
        result[name] = {'cells': data.GetNumberOfCells(), 'bounds': list(data.GetBounds()),
                        'area': sum(areas.GetTuple1(i) for i in range(data.GetNumberOfCells())),
                        'volume': sum(volumes.GetTuple1(i) for i in range(data.GetNumberOfCells())),
                        'minimumVolume': min(volumes.GetTuple1(i) for i in range(data.GetNumberOfCells())),
                        'fields': fields, 'groups': groups}
    return result


def main(action, case_path, directory, output=None):
    case = json.loads(Path(case_path).read_text()); directory = Path(directory)
    result = globals()[action](case, directory)
    if output: Path(output).write_text(json.dumps(result, allow_nan=False)+'\n')


if __name__ == '__main__':
    main(*sys.argv[1:])
