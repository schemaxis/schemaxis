"""Run with pvbatch --force-offscreen-rendering record_slice.py OUTPUT_DIRECTORY.

Record ParaView's own trace while reusing a slice, and verify geometry without
creating a representation. Outputs are experimental evidence, not an Schemaxis provider.
"""
import json
import math
from pathlib import Path
import sys

from paraview.simple import *
from paraview import smtrace

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
config = smtrace.start_trace()
config.SetFullyTraceSupplementalProxies(True)
observations = []
try:
    source = Wavelet()
    cutter = Slice(Input=source)
    cutter.SliceType = 'Plane'
    for index, x in enumerate([-5.0, 0.0, 5.0, 50.0, 0.0]):
        cutter.SliceType.Origin = [x, 0.0, 0.0]
        cutter.SliceType.Normal = [1.0, 0.0, 0.0]
        UpdatePipeline(proxy=cutter)
        info = cutter.GetDataInformation()
        bounds = list(info.GetBounds())
        ready = all(math.isfinite(v) for v in bounds) and all(
            bounds[i] <= bounds[i + 1] for i in (0, 2, 4))
        cells = info.GetNumberOfCells()
        observations.append(dict(x=x, bounds=bounds, cells=cells, ready=ready))
        if x == 50.0:
            assert not ready and cells == 0, observations[-1]
            continue
        assert ready and cells > 0, observations[-1]
        assert abs(bounds[0] - x) < 1e-6 and abs(bounds[1] - x) < 1e-6
        geometry = output / ('slice-%d.vtp' % index)
        SaveData(str(geometry), proxy=cutter)
        reader = XMLPolyDataReader(FileName=[str(geometry)])
        UpdatePipeline(proxy=reader)
        reopened = reader.GetDataInformation()
        assert reopened.GetNumberOfCells() == cells
        assert list(reopened.GetBounds()) == bounds
        Delete(reader)
    view = GetActiveViewOrCreate('RenderView')
    Show(cutter, view)
    ResetCamera(view)
    SaveScreenshot(str(output / 'slice.png'), view, ImageResolution=[400, 400])
finally:
    (output / 'trace.py').write_text(smtrace.stop_trace(), encoding='utf-8')
    (output / 'observations.json').write_text(json.dumps(observations, indent=2) + '\n')
print(json.dumps(observations))
