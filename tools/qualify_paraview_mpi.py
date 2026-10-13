#!/usr/bin/env python3
"""Bounded normal-pvbatch dispatch probe; does not qualify Schemaxis MPI workflows.

Select mpiexec from the MPI installation against which pvbatch was built.
The native script runs on the driver, while ProcessIdScalars executes on all ranks.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess


def qualify(pvbatch, mpiexec, directory, ranks=2, timeout=120):
    if type(ranks) is not int or not 2 <= ranks <= 8:
        raise ValueError('ranks must be an integer from 2 to 8')
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    script = directory / 'probe.py'
    script.write_text('''import json
from pathlib import Path
from paraview import servermanager
from paraview.simple import Sphere, ProcessIdScalars
from vtkmodules.vtkParallelCore import vtkMultiProcessController
controller = vtkMultiProcessController.GetGlobalController()
source = Sphere(ThetaResolution=64, PhiResolution=32)
# Pinned 5.13 probe: ProcessIds implicit arrays are not retained by Fetch.
partitioned = ProcessIdScalars(Input=source)
partitioned.UpdatePipeline()
data = servermanager.Fetch(partitioned)
arrays = [data.GetPointData(), data.GetCellData()]
ids = next((attributes.GetArray(name) for attributes in arrays
            for name in ('PointProcessIds', 'CellProcessIds', 'ProcessId')
            if attributes.GetArray(name) is not None), None)
assert ids is not None, 'missing process identity array'
result = {'rank': controller.GetLocalProcessId(),
          'size': controller.GetNumberOfProcesses(),
          'contributingRanks': sorted({int(ids.GetTuple1(i)) for i in range(ids.GetNumberOfTuples())}),
          'points': data.GetNumberOfPoints(), 'cells': data.GetNumberOfCells()}
Path(__file__).with_suffix('.json').write_text(json.dumps(result, indent=2))
''')
    command = [str(Path(mpiexec).absolute()), '-n', str(ranks), str(Path(pvbatch).absolute()),
               '--force-offscreen-rendering', str(script)]
    result = {'command': command, 'verified': False, 'scope': 'normal pvbatch distributed sphere and gather'}
    with (directory / 'dispatch.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            result['exitCode'] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            result['timedOut'] = True
    evidence = script.with_suffix('.json')
    if evidence.exists():
        result['observed'] = json.loads(evidence.read_text())
        observed = result['observed']
        result['verified'] = (result.get('exitCode') == 0 and observed['rank'] == 0
                              and observed['size'] == ranks
                              and observed['contributingRanks'] == list(range(ranks))
                              and observed['points'] > 0 and observed['cells'] > 0)
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pvbatch', required=True)
    parser.add_argument('--mpiexec', required=True)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--ranks', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    result = qualify(args.pvbatch, args.mpiexec, args.output_directory, args.ranks, args.timeout)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['verified'] else 1)
