"""Coordinator-only analytic fixture generation and independent artifact grading.

Run inside pvbatch. No Schemaxis imports or producer receipts are used.
"""
import json
import math
from pathlib import Path
import sys


def near(actual, expected, tolerance=2e-6):
    if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance):
        raise ValueError(f'{actual} differs from {expected}')


def fixture(case, directory):
    from vtkmodules.vtkCommonCore import vtkDoubleArray
    from vtkmodules.vtkCommonDataModel import vtkImageData
    from vtkmodules.vtkIOXML import vtkXMLImageDataWriter
    directory.mkdir(parents=True)
    entries = []
    for time in (0, 1, 2):
        data = vtkImageData()
        data.SetDimensions(9, 7, 5)
        data.SetSpacing(case['length']/8, case['width']/6, case['height']/4)
        points, cells = vtkDoubleArray(), vtkDoubleArray()
        points.SetName('T'); cells.SetName('T')
        for i in range(data.GetNumberOfPoints()):
            x, y, z = data.GetPoint(i)
            points.InsertNextValue(case['offset'] + 2*x + 3*y + 5*z + 7*time)
        for i in range(data.GetNumberOfCells()):
            cells.InsertNextValue(80 + case['offset'] + 11*time)
        data.GetPointData().AddArray(points); data.GetCellData().AddArray(cells)
        writer = vtkXMLImageDataWriter()
        writer.SetFileName(str(directory/f'time-{time}.vti'))
        writer.SetInputData(data); writer.SetDataModeToAscii()
        assert writer.Write()
        entries.append(f'<DataSet timestep="{time}" group="" part="0" file="time-{time}.vti"/>')
    (directory/'series.pvd').write_text('<VTKFile type="Collection" version="0.1" byte_order="LittleEndian"><Collection>' + ''.join(entries) + '</Collection></VTKFile>')
    (directory/'PROVENANCE.json').write_text(json.dumps({
        'origin': 'Synthetic analytic field; not a solved CFD case',
        'point T': 'offset + 2*x + 3*y + 5*z + 7*time',
        'cell T': '80 + offset + 11*time', 'case': case}, indent=2))


def image(path):
    from vtkmodules.vtkIOImage import vtkPNGReader
    from vtkmodules.util.numpy_support import vtk_to_numpy
    reader = vtkPNGReader(); reader.SetFileName(str(path)); reader.Update()
    data = reader.GetOutput()
    values = data.GetPointData().GetScalars()
    if values is None: raise ValueError('cannot decode image '+str(path))
    return data.GetDimensions()[:2], vtk_to_numpy(values)[:, :3].astype(float)


def check_image(actual, expected):
    import numpy as np
    dims, a = image(actual); reference_dims, b = image(expected)
    if dims != reference_dims: raise ValueError('image dimensions differ')
    error = np.abs(a-b)
    mae = float(error.mean()); bad = float((error.max(axis=1) > 12).mean())
    # Same native renderer, specified camera/colour mapping. Small raster-edge
    # variations are tolerated, but blank/stale/wrong-view/auto-scaled images fail.
    if mae > 2.0 or bad > .025:
        raise ValueError(f'image differs: mean channel error {mae:.4f}, bad pixels {bad:.4f}')
    return {'meanChannelError': mae, 'badPixelFraction': bad}


def check_geometry(case, time, fraction, path):
    from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
    from vtkmodules.vtkFiltersVerdict import vtkCellSizeFilter
    reader = vtkXMLPolyDataReader(); reader.SetFileName(str(path)); reader.Update()
    data = reader.GetOutput()
    if not data.GetNumberOfCells() or not data.GetNumberOfPoints(): raise ValueError('empty slice')
    lengths = [case['length'], case['width'], case['height']]
    axis = case['sliceAxis']; coordinate = lengths[axis]*fraction
    bounds = [0, lengths[0], 0, lengths[1], 0, lengths[2]]
    bounds[2*axis:2*axis+2] = [coordinate, coordinate]
    for a, b in zip(data.GetBounds(), bounds): near(a, b)
    points = data.GetPointData().GetArray('T'); cells = data.GetCellData().GetArray('T')
    if points is None or cells is None: raise ValueError('both POINTS T and CELLS T required')
    if points.GetNumberOfComponents()!=1 or cells.GetNumberOfComponents()!=1: raise ValueError('T must be scalar')
    for i in range(data.GetNumberOfPoints()):
        x, y, z = data.GetPoint(i)
        near(points.GetTuple1(i), case['offset']+2*x+3*y+5*z+7*time)
        near((x,y,z)[axis], coordinate)
    for i in range(data.GetNumberOfCells()): near(cells.GetTuple1(i),80+case['offset']+11*time)
    size = vtkCellSizeFilter(); size.SetInputData(data); size.Update()
    areas = size.GetOutput().GetCellData().GetArray('Area')
    area = sum(areas.GetTuple1(i) for i in range(areas.GetNumberOfTuples()))
    expected_area = math.prod(lengths[i] for i in range(3) if i != axis)
    near(area, expected_area)
    return {'cells': data.GetNumberOfCells(), 'points': data.GetNumberOfPoints(), 'area': area}


def grade(task, submission, reference):
    records=[]
    for case in task['cases']:
        checks=[]; errors=[]
        for ti, time in enumerate(case['times']):
            for si, fraction in enumerate(case['fractions']):
                stem=f'slice-{ti}-{si}'
                geometry=submission/case['id']/(stem+'.vtp')
                try: checks.append({'file':geometry.name, **check_geometry(case,time,fraction,geometry)})
                except Exception as error: errors.append({'file':geometry.name,'error':str(error)})
                for ai in range(len(task['appearances'])):
                    for ci in range(len(case['cameras'])):
                        name=f'{stem}-appearance-{ai}-camera-{ci}.png'
                        try: checks.append({'file':name, **check_image(submission/case['id']/name,reference/case['id']/name)})
                        except Exception as error: errors.append({'file':name,'error':str(error)})
        records.append({'id':case['id'],'passed':not errors,'checks':checks,'errors':errors})
    return {'passed':all(c['passed'] for c in records),'cases':records,
            'scope':'analytic geometry/point and cell values; decoded pixels against independently rendered camera/colour references'}


if __name__ == '__main__':
    action, task_path, destination = sys.argv[1:4]
    task=json.loads(Path(task_path).read_text()); destination=Path(destination)
    if action=='fixture':
        for case in task['cases']: fixture(case,destination/case['id'])
    elif action=='grade':
        Path(sys.argv[5]).write_text(json.dumps(grade(task,destination,Path(sys.argv[4])),indent=2)+'\n')
    else: raise ValueError(action)
