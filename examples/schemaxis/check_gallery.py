"""Independent geometry expectations for blender-gallery.json."""
import json
import math
from pathlib import Path
import sys


def check(directory):
    receipt = json.loads((Path(directory)/'verification.json').read_text())
    assert receipt['status'] == 'succeeded'
    assert receipt['renderSettings']['device'] == 'OPTIX'
    assert any(d['type'] == 'OPTIX' for d in receipt['devices'])
    observations = receipt['states'][0]['observations']
    def volume(name, expected, tolerance=1e-5):
        assert math.isclose(observations[name]['signedVolume'], expected, rel_tol=tolerance), name
    volume('uvSphere', 4*math.pi/3, .02)
    volume('cylinder', 2*math.pi, .01)
    volume('cone', 2*math.pi/3, .01)
    volume('torus', 2*math.pi**2*.25**2, .04)
    volume('solidify', .4)
    volume('boolean', 4)
    volume('triangulate', 8)
    volume('array', 16)
    assert observations['triangulate']['cells'] == 12
    assert observations['subdivision']['cells'] > observations['box']['cells']
    assert observations['decimate']['points'] < observations['box']['points']
    assert 0 < observations['smooth']['signedVolume'] < 8
    for name in ['solidify','subdivision','decimate','triangulate','smooth','array','mirror','boolean']:
        volume(name+'Placed', observations[name]['signedVolume'])
    return {'verified':True, 'checks':['primitive analytic volumes','solidify thickness',
            'boolean half-cube difference','triangulation preserves volume',
            'array doubles volume','subdivision and decimation topology','smooth shrinks cube',
            'translation preserves volume','OptiX evidenced']}


if __name__ == '__main__':
    print(json.dumps(check(sys.argv[1]), indent=2))
