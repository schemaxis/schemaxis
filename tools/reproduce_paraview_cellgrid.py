# Copyright (C) 2026 David L F Gaden
"""Native-only reproduction of the recorded 5.13.3 cell-grid probe failure.

Run with pvpython. No Schemaxis imports: reports whether a tiny interior-point
probe produces nonfinite coordinates/values despite finding containing cells.
"""
import json
import math
from paraview import simple as pv

sphere=pv.Sphere()
volume=pv.Delaunay3D(Input=sphere)
cells=pv.ConvertToCellGrid(Input=volume)
height=pv.CellGridElevation(Input=cells,AttributeName='height')
points=pv.PointSource(NumberOfPoints=5,Radius=0.1)
probe=pv.CellGridProbe(Input=points,Source=height)
# The installed XML omits this string property's initial element count.
prop=probe.GetProperty('CellGridAttribute')
if prop.SMProperty.GetNumberOfElements()==0:prop.SMProperty.SetNumberOfElements(1)
probe.CellGridAttribute='height'
probe.UpdatePipeline()
data=probe.GetClientSideObject().GetOutputDataObject(0)
iterator=data.NewIterator();iterator.InitTraversal()
leaf=iterator.GetCurrentDataObject();arrays=leaf.GetPointData()
result={'nativeVersion':pv.GetParaViewSourceVersion(),'points':leaf.GetNumberOfPoints(),
        'containingCells':[int(arrays.GetArray('ContainingCellID').GetTuple1(i)) for i in range(leaf.GetNumberOfPoints())],
        'nonfiniteArrays':[]}
for i in range(arrays.GetNumberOfArrays()):
    array=arrays.GetArray(i)
    if any(not math.isfinite(value) for j in range(array.GetNumberOfTuples()) for value in array.GetTuple(j)):
        result['nonfiniteArrays'].append(array.GetName())
print(json.dumps(result,indent=2))
for proxy in [probe,points,height,cells,volume,sphere]:pv.Delete(proxy)
raise SystemExit(1 if result['nonfiniteArrays'] else 0)
