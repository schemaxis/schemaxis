# Copyright (C) 2026 David L F Gaden
"""Reusable ordinary ParaView recipe. Invoke with pvbatch --force-offscreen-rendering.

Usage: pvbatch native_recipe.py task.json submission
The task owns case lists, physical slice positions, times, views and appearances.
This is also the coordinator's independent rendering reference implementation.
"""
import json
import math
from pathlib import Path
import sys
from paraview import simple as p


def execute(task, output):
    p._DisableFirstRenderCameraReset()
    view=p.CreateView('RenderView'); view.OrientationAxesVisibility=0
    view.UseColorPaletteForBackground=0; view.Background=[1,1,1]
    view.ViewSize=task['imageSize']
    for case in task['cases']:
        folder=output/case['id']; folder.mkdir(parents=True,exist_ok=True)
        source=p.PVDReader(FileName=str(Path(task['inputs'])/case['id']/'series.pvd'))
        source.PointArrays=['T']; source.CellArrays=['T']
        cut=p.Slice(Input=source); cut.SliceType='Plane'
        axis=case['sliceAxis']; lengths=[case['length'],case['width'],case['height']]
        normal=[0,0,0]; normal[axis]=1; cut.SliceType.Normal=normal
        display=p.Show(cut,view); display.Representation='Surface'; display.Opacity=1
        for ti,time in enumerate(case['times']):
            view.ViewTime=time
            for si,fraction in enumerate(case['fractions']):
                origin=[0,0,0]; origin[axis]=lengths[axis]*fraction
                cut.SliceType.Origin=origin; cut.UpdatePipeline(time=time)
                stem=f'slice-{ti}-{si}'
                p.SaveData(str(folder/(stem+'.vtp')),proxy=cut)
                for ai,appearance in enumerate(task['appearances']):
                    p.ColorBy(display,tuple(appearance['field']),separate=True)
                    lut=p.GetColorTransferFunction(appearance['field'][1],display,separate=True)
                    if not lut.ApplyPreset(appearance['preset'],True): raise ValueError('unknown preset')
                    lut.VectorMode='Magnitude'; lut.UseLogScale=0
                    lut.RescaleTransferFunction(*appearance['range'])
                    display.SetScalarBarVisibility(view,False)
                    for ci,camera in enumerate(case['cameras']):
                        focal=[n/2 for n in lengths]; focal[axis]=origin[axis]
                        direction=camera['direction']; norm=math.sqrt(sum(x*x for x in direction))
                        view.CameraFocalPoint=focal
                        view.CameraPosition=[focal[i]+direction[i]/norm*camera['distance'] for i in range(3)]
                        view.CameraViewUp=camera['up']; view.CameraParallelProjection=1
                        view.CameraParallelScale=camera['scale']
                        p.Render(view)
                        p.SaveScreenshot(str(folder/f'{stem}-appearance-{ai}-camera-{ci}.png'),view,ImageResolution=task['imageSize'])
        p.Delete(display); p.Delete(cut); p.Delete(source)
    p.Delete(view)


if __name__=='__main__':
    execute(json.loads(Path(sys.argv[1]).read_text()),Path(sys.argv[2]))
