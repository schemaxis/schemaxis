"""Native CAD, measured drawing, mesh and animated product-handoff acceptance."""
import argparse
import json
import math
from pathlib import Path

from schemaxis import workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json
from schemaxis.png import read as read_png

ROOT = Path(__file__).resolve().parents[1]


def near(actual, expected, tolerance=1e-7):
    assert math.isfinite(actual) and math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance), (actual, expected)


def inspect(result, variant):
    jobs = {job['operation']: Path(job['directory']) for job in result['jobs']}
    volume = 10212.5+52*math.pi if variant else 10128+60*math.pi
    moment = 84009.375+388*math.pi if variant else 80472+414*math.pi
    height, floor, wall = (22, 3.5, 2.5) if variant else (20, 3, 3)
    cad = json.loads((jobs['housing']/'verification.json').read_text())
    near(cad['native']['volume'], volume)
    near(cad['exportEvidence']['native']['centreOfMass'][2], moment/volume)
    lid = json.loads((jobs['lid']/'verification.json').read_text())
    near(lid['native']['volume'], floor*(1200-24-math.pi))
    mesh = json.loads((jobs['analysisMesh']/'mesh-summary.json').read_text())
    near(mesh['cadVolume'], volume)
    faces = {face['name']: face for face in mesh['boundaryAreaChecks']}
    near(faces['mountingFloor']['cadArea'], 1200-4*math.pi)
    near(faces['lidRim']['cadArea'], 1200-(40-2*wall)*(30-2*wall))
    assert abs(mesh['volume']/volume-1) < .003
    sheet = json.loads((jobs['manufacturingDrawing']/'verification.json').read_text())
    dimensions = {item['id']: item for item in sheet['dimensions']}
    for identity, value in [('width', 40), ('height', height), ('wall', wall)]:
        dimension = dimensions[identity]
        axis = 1 if identity=='height' else 0
        endpoints = dimension['linear']
        scale = next(view['scale'] for view in sheet['views']
                     if view['name']==dimension['references'][0][0])
        near(abs(endpoints[0][axis]-endpoints[1][axis])/scale, value)
    rendering = json.loads((jobs['productRendering']/'verification.json').read_text())
    asset = next(item for item in rendering['artifacts'] if item['kind']=='asset')
    assert asset['units']=='metres' and asset['frame']==7
    near(asset['after']['signedVolume'], (volume+floor*(1200-24-math.pi))*1e-9, 2e-8)
    assert abs(asset['after']['signedVolume']/((volume+floor*(1200-24-math.pi))*1e-9)-1) < .002
    intent = rendering['states'][0]['production']['intents'][0]
    near(intent['pivot'][0], 0, 1e-6)
    near(intent['pivot'][1], 0, 1e-6)
    near(intent['pivot'][2], ((.029+.0035) if variant else .030)/2, 1e-6)
    images = [item for item in rendering['artifacts'] if item.get('productionOutput') and item['kind']=='image']
    assert [item['frame'] for item in images] == [1, 7, 13]
    pixels = []
    for image in images:
        width, height_px, rgba = read_png(image['file'])
        assert (width, height_px) == (640, 480)
        luminance = [sum(rgba[i:i+3]) for i in range(0, len(rgba), 4)]
        assert max(luminance)-min(luminance) > 100, 'render has no useful tonal variation'
        pixels.append(rgba)
    assert all(a != b for a, b in zip(pixels, pixels[1:])), 'turntable frames are unchanged'
    from schemaxis.adaptors import registry
    structural=registry.verify(jobs['structuralAnalysis'])['analysis']
    near(structural['appliedForceN'][2], -.1*(1200-(40-2*wall)*(30-2*wall)), 2e-5)
    assert math.hypot(*structural['forceResidualN'])<.001
    assert math.hypot(*structural['momentResidualNMM'])<.02
    assert 0<structural['maxDisplacementMM']<.001
    assert math.isclose(structural['strainEnergyNMM'],structural['externalWorkNMM'],rel_tol=.005)
    return {'analyticHousingVolumeMM3': volume, 'analyticHousingCentreZMM': moment/volume,
            'analyticLidVolumeMM3': floor*(1200-24-math.pi), 'drawingDimensionsMM': [40, height, wall],
            'frameImages': 3, 'tonalVariationAndMotion': True,
            'structuralAnalysis':{key:structural[key] for key in ('maxDisplacementMM','appliedForceN',
                'reactionForceN','forceResidualN','momentResidualNMM','strainEnergyNMM','externalWorkNMM')},
            'limits': 'Demonstration linear elasticity; no stress allowance, manufacturing tolerance or safety certification.'}


def qualify(directory, locations, *, resume=False):
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=resume)
    identities = {app: source_digest(app) for app in ('freecad', 'gmsh', 'blender')}
    report = {'verified': False, 'sourceDigests': identities, 'cases': {}}
    try:
        for name, variant in [('baseline', False), ('variant', True)]:
            filename = 'enclosure-manufacturing-rendering-'+('variant' if variant else 'workflow')+'.json'
            document = json.loads((ROOT/'examples/schemaxis'/filename).read_text())
            target = directory/name
            result = workflow.execute(document, target, locations=locations, timeout=300,
                                      resume=resume and target.exists())
            assert workflow.verify(target)['verified']
            report['cases'][name] = inspect(result, variant)
            reused = workflow.execute(document, target, locations=locations, timeout=300, resume=True)
            assert all(job['reused'] for job in reused['jobs'])
            # A damaged downstream publication must invalidate its owning branch
            # while the verified CAD, mesh and product-render branches remain usable.
            jobs = {job['operation']: Path(job['directory']) for job in reused['jobs']}
            (jobs['manufacturingDrawing']/'drawing.svg').write_text('damaged drawing publication')
            repaired = workflow.execute(document, target, locations=locations, timeout=300, resume=True)
            state = {job['operation']: job['reused'] for job in repaired['jobs']}
            assert state == {'housing': True, 'lid': True, 'analysisMesh': True,
                             'manufacturingDrawing': False,'structuralAnalysis':True, 'productRendering': True}, state
            assert workflow.verify(target)['verified']
            inspect(repaired, variant)
            report['cases'][name]['reuseAfterDrawingDamage'] = state
            atomic_json(directory/'report.json', report)
        assert identities == {app: source_digest(app) for app in identities}, 'adaptor source changed during acceptance'
        report['verified'] = True
    finally:
        atomic_json(directory/'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--freecad', required=True)
    parser.add_argument('--freecad-gui', required=True)
    parser.add_argument('--gmsh', required=True)
    parser.add_argument('--blender', required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    print(json.dumps(qualify(args.directory, {'freecad': args.freecad, 'freecad_gui': args.freecad_gui,
                                           'gmsh': args.gmsh, 'blender': args.blender}, resume=args.resume), indent=2))
