"""Independent analytic checks for the CAD -> ParaView -> Blender example.

Run with PYTHONPATH=src python3 examples/schemaxis/check_freecad_gallery.py OUTPUT.
"""
import json
import math
from pathlib import Path
import sys
from schemaxis.workflow import verify


def check(directory):
    directory=Path(directory).resolve()
    result=verify(directory)
    jobs=json.loads((directory/'result.json').read_text())['jobs']
    # Successful attempt paths are retained by the coordinator; never guess latest.
    paths={job['operation']:Path(job['directory']) for job in jobs}
    expectations={
        'bracket':{'volume':100*70*8+100*8*60-100*8*8-2*math.pi*5**2*8-2*math.pi*6**2*8,
                   'bounds':[0,100,0,70,0,60]},
        'flange':{'volume':math.pi*(35**2*8+18**2*52-12**2*60-4*3.5**2*8),
                  'bounds':[-35,35,-35,35,0,60]},
    }
    checks={}
    for identity,expected in expectations.items():
        cad=json.loads((paths[identity]/'verification.json').read_text())
        render=json.loads((paths[identity+'Render']/'verification.json').read_text())
        observed=render['states'][0]['observations']['styled']
        for kind in ('native','step'):
            assert math.isclose(cad[kind]['volume'],expected['volume'],rel_tol=1e-9,abs_tol=1e-6), (identity,kind)
            assert all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(cad[kind]['bounds'],expected['bounds']))
        assert len(observed['bounds'])==6
        assert all(math.isclose(a,b*0.001,abs_tol=2e-7) for a,b in zip(observed['bounds'],expected['bounds'])), 'axis/unit conversion failed'
        assert math.isclose(observed['signedVolume'],expected['volume']*1e-9,rel_tol=0.005), 'mesh volume/handedness failed'
        checks[identity]={'analyticVolumeMM3':expected['volume'],'nativeVolumeMM3':cad['native']['volume'],
                          'meshVolumeMM3':cad['mesh']['volume'],'blenderVolumeM3':observed['signedVolume'],
                          'blenderBoundsM':observed['bounds'],'cadDirectory':str(paths[identity]),
                          'renderDirectory':str(paths[identity+'Render'])}
    return {**result,'checks':checks,'scope':'analytic volumes, CAD round trips, watertight meshes, explicit mm-to-m and glTF axis conversion'}


if __name__=='__main__':
    print(json.dumps(check(sys.argv[1]),indent=2))
