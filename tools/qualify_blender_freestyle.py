"""Public Freestyle geometry/raster qualification; no workstation paths.

Run under the repository's bounded runner. The separate lifecycle qualifier adds
captured-input retirement and refreshed native/witness attacks.
"""
import argparse
import copy
import json
import math
from pathlib import Path

from schemaxis.adaptors.blender.adaptor import run, verify
from schemaxis.configuration import location_context
from schemaxis.png import read
from blender_surface_evidence import identity, verify_identity


def emission(identity):
    return {'id': identity, 'nodes': [
        {'id': 'emit', 'kind': 'emission', 'values': {'colour': [1, 1, 1, 1]}},
        {'id': 'finish', 'kind': 'output'}], 'links': [
        {'from': {'node': 'emit', 'socket': 'shader'},
         'to': {'node': 'finish', 'socket': 'surface'}}]}


def quad(identity, x0, x1, z0, z1, y, collection='parts'):
    return {'id': identity, 'kind': 'mesh', 'collection': collection, 'material': 'white',
            'vertices': [[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]],
            'faces': [[0, 1, 2, 3]]}


def line_intent(sphere=False, width=None):
    styles = [{'id': 'visible', 'width': width or (4 if sphere else 3), 'colour': [0, 0, 1, 1]},
              {'id': 'hidden', 'width': 2, 'colour': [1, 0, 0, 1], 'dash': [{'length': 7, 'gap': 3}]}]
    sets = [{'id': 'visible_edges', 'style': 'visible', 'edges': ['border', 'silhouette'],
             'scope': {'kind': 'objects', 'objects': ['source']}, 'visibility': {'kind': 'visible'}},
            {'id': 'hidden_edges', 'style': 'hidden', 'edges': ['border', 'silhouette'],
             'scope': {'kind': 'collection', 'collection': 'parts'},
             'visibility': {'kind': 'range', 'minimum': 1, 'maximum': 1}}]
    materials = []
    if sphere:
        styles.append({'id': 'boundary', 'width': 3, 'colourSource': 'materialLine'})
        sets.append({'id': 'material_edges', 'style': 'boundary', 'edges': ['materialBoundary'],
                     'scope': {'kind': 'objects', 'objects': ['source']}, 'visibility': {'kind': 'visible'}})
        materials = [{'material': 'upper', 'colour': [0, 0, 1, 1], 'priority': 1},
                     {'material': 'lower', 'colour': [0, 1, 0, 1], 'priority': 9}]
    return {'styles': styles, 'materials': materials,
            'layers': [{'layer': 'technical', 'lineSets': sets}]}


def sphere_mesh():
    """Explicit closed latitude mesh; no native primitive in the oracle."""
    segments, rings = 64, 32
    points = [[0, 0, 1]]
    for row in range(1, rings):
        theta = math.pi*row/rings
        points.extend([[math.sin(theta)*math.cos(2*math.pi*i/segments),
                        math.sin(theta)*math.sin(2*math.pi*i/segments), math.cos(theta)]
                       for i in range(segments)])
    bottom = len(points); points.append([0, 0, -1])
    faces = [[0, 1+i, 1+(i+1) % segments] for i in range(segments)]
    for row in range(rings-2):
        a, b = 1+row*segments, 1+(row+1)*segments
        faces.extend([[a+i, b+i, b+(i+1) % segments, a+(i+1) % segments] for i in range(segments)])
    a = 1+(rings-2)*segments
    faces.extend([[bottom, a+(i+1) % segments, a+i] for i in range(segments)])
    upper = [i for i, face in enumerate(faces) if sum(points[v][2] for v in face) > 0]
    return {'id': 'source', 'kind': 'mesh', 'vertices': points, 'faces': faces,
            'location': [.75, 0, .25], 'smooth': True, 'collection': 'parts', 'material': 'upper'}, upper


def fixture(kind='plate', width=None, excluded=False):
    sphere = kind == 'sphere'
    production = {'collections': [{'id': 'parts'}, {'id': 'occluders'}],
                  'viewLayers': [{'id': 'technical', 'passes': ['combined']}],
                  'materialGraphs': [emission('white')], 'npr': line_intent(sphere, width)}
    if sphere:
        source, upper = sphere_mesh()
        production['objects'] = [source, quad('occluder', .2, .6, -2, 2, -2, 'occluders')]
        production['materialGraphs'].extend([emission('upper'), emission('lower')])
        production['materialAssignments'] = [{'id': 'hemispheres', 'kind': 'layout', 'object': 'source',
            'sharing': 'refuse', 'slots': [{'id': 'top', 'material': 'upper'}, {'id': 'bottom', 'material': 'lower'}],
            'defaultSlot': 'bottom', 'regions': [{'slot': 'top', 'selection': {'kind': 'faceIndices', 'indices': upper}}]}]
    else:
        production['objects'] = [quad('source', -2, 2, -1.5, 1.5, 0),
                                 quad('occluder', -.5, .5, -2, 2, -1, 'occluders')]
    if excluded:
        production['viewLayers'][0]['collections'] = [
            {'target': {'kind': 'collection', 'collection': 'parts'}, 'mode': 'exclude'}]
    return {'version': 'schemaxis.blender.production/1', 'size': [320 if sphere else 256, 256],
            'cameras': [{'direction': [0, -1, 0], 'up': [0, 0, 1], 'parallel': True,
                         'focalPoint': [0, 0, .25 if sphere else 0], 'scale': 7.5 if sphere else 8, 'distance': 10}],
            'render': {'samples': 1, 'threads': 2, 'denoise': False, 'renderer': {'kind': 'cycles'},
                       'worldColour': [1, 1, 1], 'worldStrength': 1, 'lightEnergy': 0,
                       'colourManagement': {'view': {'kind': 'standard'}}}, 'production': production}


def pixels(image, x0, x1, y0, y1):
    width, height, data = image
    assert 0 <= x0 <= x1 < width and 0 <= y0 <= y1 < height
    return [(x, y, tuple(data[4*(y*width+x):4*(y*width+x)+4]))
            for y in range(y0, y1+1) for x in range(x0, x1+1)]


def colour(pixel, channel):
    return pixel[channel] > 200 and all(pixel[i] < 100 for i in range(3) if i != channel)


def near_colour(image, x, y, channel, radius=3):
    return sum(colour(p, channel) for _, _, p in pixels(image, int(x)-radius, int(x)+radius, int(y)-radius, int(y)+radius))


def linear(byte):
    value = byte/255
    return value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4


def plate_oracle(image):
    assert image[:2] == (256, 256)
    assert near_colour(image, 64, 128, 2) >= 3
    assert near_colour(image, 90, 80, 2) >= 3
    assert not any(colour(p, 2) for _, _, p in pixels(image, 116, 139, 78, 82))
    red = [any(colour(p, 0) for _, _, p in pixels(image, x, x, 78, 82)) for x in range(114, 142)]
    assert 5 <= sum(red) <= 23 and sum(a != b for a, b in zip(red, red[1:])) >= 3, red
    weights = [(x+.5, 1-linear(p[0])) for x, _, p in pixels(image, 58, 70, 128, 128)]
    mass = sum(w for _, w in weights); centre = sum(x*w for x, w in weights)/mass
    assert abs(mass-3) <= 1 and abs(centre-64) <= .75, (mass, centre)
    return {'literalEdgePixelX': 64, 'edgePixelCentre': centre, 'coverageWidth': mass,
            'hiddenDashColumns': red, 'hiddenExpectedPixelInterval': [112, 144]}


def sphere_oracle(image, width=4):
    assert image[:2] == (320, 256)
    cx, cy, radius = 192, 128, 256/6
    for angle in (0, math.pi/4, math.pi/2):
        assert near_colour(image, cx+radius*math.cos(angle), cy-radius*math.sin(angle), 2, 4) >= 2
    blue = [(x+.5, y+.5) for x, y, p in pixels(image, 140, 245, 76, 180) if colour(p, 2)]
    chord = radius*(1-math.cos(math.sqrt(2)*math.pi/32)); bound = width/2+1.5+chord
    assert blue and max(abs(math.hypot(x-cx, y-cy)-radius) for x, y in blue) <= bound
    assert sum(colour(p, 1) for _, _, p in pixels(image, 211, 226, 126, 130)) >= 8
    assert sum(colour(p, 0) for _, _, p in pixels(image, 171, 186, 82, 95)) >= 2
    mass = sum(1-linear(p[0]) for _, _, p in pixels(image, 192, 192, 77, 94))
    assert abs(mass-width) <= 1, (mass, width)
    return {'literalCircle': [cx, cy, radius], 'prospectiveRasterChordBound': bound,
            'coverageWidthAtCircleTop': mass, 'materialBoundaryExpected': 'green higher-priority lower Material'}


def image(directory):
    receipt = json.loads((Path(directory)/'verification.json').read_text())
    paths = [Path(a['file']) for a in receipt['artifacts'] if a.get('kind') == 'image']
    assert len(paths) == 1, paths
    return read(paths[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True); parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); out = args.output.absolute(); out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', **identity(out, args.blender), 'checks': []}; target = out/'summary.json'
    def record(case, **value):
        report['checks'].append({'case': case, **value}); target.write_text(json.dumps(report, indent=2)+'\n'); print(case+' PASS', flush=True)
    try:
        for label, document, oracle in [('occluded-plate', fixture(), plate_oracle),
                ('material-sphere', fixture('sphere'), sphere_oracle),
                ('wider-sphere', fixture('sphere', 6), lambda p: sphere_oracle(p, 6))]:
            packet = out/label; run(document, packet, executable=args.blender, timeout=240)
            with location_context({'blender': args.blender}): assert verify(packet)['verified']
            record(label, independentRaster=oracle(image(packet)), savedFreshProcessPublicVerify=True)
        packet = out/'excluded-source'; run(fixture(excluded=True), packet, executable=args.blender, timeout=240)
        with location_context({'blender': args.blender}): assert verify(packet)['verified']
        w, h, data = image(packet); assert (w, h) == (256, 256)
        assert all(min(data[i:i+3]) >= 254 for i in range(0, len(data), 4))
        record('excluded-source', zeroLines=True, zeroSurface=True)
        verify_identity(report, args.blender); report['status'] = 'passed'
    finally:
        if report['status'] == 'running': report['status'] = 'failed'
        target.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__': main()
