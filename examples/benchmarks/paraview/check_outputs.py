# Copyright (C) 2026 David L F Gaden
"""Bounded publication checks for the analytic ParaView recipe examples.

Run with pvbatch. This checks actual geometry, fields, image dimensions/content
and optional saved hashes. It does NOT certify image camera, colour range or time.
It has no access to benchmark references and does not render replacement outputs.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_digest(task):
    root = Path(task['inputs'])
    return digest({str(p.relative_to(root)): file_digest(p)
                   for case in task['cases'] for p in sorted((root/case['id']).rglob('*'))
                   if p.is_file()})


def check_baseline(baseline, task, inputs, files):
    """A saved manifest proves unchanged bytes, not semantic correctness."""
    errors = []
    if baseline.get('taskDigest') != digest(task):
        errors.append('saved task differs; check fresh outputs and record a new manifest')
    if baseline.get('inputDigest') != inputs:
        errors.append('saved input bytes differ; check fresh outputs and record a new manifest')
    old = baseline.get('files', {})
    for name in sorted(set(old) | set(files)):
        if old.get(name) != files.get(name):
            errors.append('publication changed or missing: '+name)
    return errors


def near(actual, expected):
    if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=2e-6, abs_tol=2e-6):
        raise ValueError(f'{actual} differs from {expected}')


def geometry(path, case, time, fraction):
    from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
    from vtkmodules.vtkFiltersVerdict import vtkCellSizeFilter
    reader = vtkXMLPolyDataReader(); reader.SetFileName(str(path)); reader.Update()
    data = reader.GetOutput()
    if not data.GetNumberOfPoints() or not data.GetNumberOfCells():
        raise ValueError('empty geometry')
    extents = [case['length'], case['width'], case['height']]
    axis = case['sliceAxis']; plane = extents[axis]*fraction
    bounds = [0, extents[0], 0, extents[1], 0, extents[2]]
    bounds[2*axis:2*axis+2] = [plane, plane]
    for actual, expected in zip(data.GetBounds(), bounds):
        near(actual, expected)
    points = data.GetPointData().GetArray('T'); cells = data.GetCellData().GetArray('T')
    if points is None or cells is None or points.GetNumberOfComponents() != 1 or cells.GetNumberOfComponents() != 1:
        raise ValueError('scalar POINTS T and CELLS T are required')
    for i in range(data.GetNumberOfPoints()):
        x, y, z = data.GetPoint(i)
        near((x, y, z)[axis], plane)
        near(points.GetTuple1(i), case['offset']+2*x+3*y+5*z+7*time)
    for i in range(data.GetNumberOfCells()):
        near(cells.GetTuple1(i), 80+case['offset']+11*time)
    sizes = vtkCellSizeFilter(); sizes.SetInputData(data); sizes.Update()
    areas = sizes.GetOutput().GetCellData().GetArray('Area')
    near(sum(areas.GetTuple1(i) for i in range(areas.GetNumberOfTuples())),
         math.prod(extents[i] for i in range(3) if i != axis))


def image(path, size):
    from vtkmodules.vtkIOImage import vtkPNGReader
    from vtkmodules.util.numpy_support import vtk_to_numpy
    reader = vtkPNGReader(); reader.SetFileName(str(path)); reader.Update()
    data = reader.GetOutput(); values = data.GetPointData().GetScalars()
    if list(data.GetDimensions()[:2]) != size or values is None or values.GetNumberOfComponents() < 3:
        raise ValueError('image dimensions/components differ or cannot decode PNG')
    rgb = vtk_to_numpy(values)[:, :3]
    if not (rgb.min(axis=1) < 240).any() or not (rgb.min(axis=1) > 250).any():
        raise ValueError('expected visible surface and white background')


def check(task, submission, baseline=None):
    files, cases, errors = {}, [], []
    expected_cases = {case['id'] for case in task['cases']}
    actual_cases = {p.name for p in submission.iterdir() if p.is_dir()} if submission.is_dir() else set()
    if actual_cases != expected_cases:
        errors.append('submission case directories differ from task')
    for case in task['cases']:
        failures = []; count = 0
        for ti, time in enumerate(case['times']):
            for si, fraction in enumerate(case['fractions']):
                stem = f'slice-{ti}-{si}'
                requests = [(stem+'.vtp', None)]
                requests += [(f'{stem}-appearance-{ai}-camera-{ci}.png', 'image')
                             for ai in range(len(task['appearances'])) for ci in range(len(case['cameras']))]
                for name, kind in requests:
                    path = submission/case['id']/name; relative = str(path.relative_to(submission))
                    try:
                        if not path.is_file():
                            raise ValueError('missing publication')
                        files[relative] = file_digest(path)
                        if kind == 'image': image(path, task['imageSize'])
                        else: geometry(path, case, time, fraction)
                        count += 1
                    except Exception as error:
                        failures.append({'file': relative, 'error': str(error)})
        cases.append({'id': case['id'], 'passed': not failures, 'publicationsChecked': count, 'errors': failures})
    inputs = input_digest(task)
    if baseline is not None:
        errors.extend(check_baseline(baseline, task, inputs, files))
    return {'passed': not errors and all(c['passed'] for c in cases), 'cases': cases,
            'errors': errors, 'taskDigest': digest(task), 'inputDigest': inputs, 'files': files,
            'scope': 'analytic geometry/fields; PNG dimensions and nonblank surface/background; optional unchanged-byte checks',
            'notChecked': ['image camera correctness', 'image colour mapping', 'image time correctness'],
            'baselineMeaning': 'unchanged bytes since this bounded check; not independent semantic certification'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', type=Path); parser.add_argument('submission', type=Path)
    parser.add_argument('--baseline', type=Path, help='require task, inputs and publications to match saved manifest')
    parser.add_argument('--record', type=Path, help='write new manifest only when checks pass')
    args = parser.parse_args()
    result = check(json.loads(args.task.read_text()), args.submission,
                   json.loads(args.baseline.read_text()) if args.baseline else None)
    if args.record and result['passed']:
        args.record.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
