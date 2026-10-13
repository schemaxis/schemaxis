"""Independent acceptance checks for the ParaView-to-Blender wireframe example."""
import json
import math
from pathlib import Path
import sys


def check(directory):
    receipt = json.loads((Path(directory) / 'verification.json').read_text())
    assert receipt['status'] == 'succeeded'
    assert len(receipt['states']) == 2
    volumes = []
    for state in receipt['states']:
        source, styled, cage = (state['observations'][key] for key in ('imported', 'styled', 'cage'))
        assert source == styled, 'material assignment changed geometry'
        assert math.isclose(source['signedVolume'], 4*math.pi*8/3, rel_tol=.03)
        assert cage['points'] > source['points'] and cage['cells'] > source['cells']
        assert 0 < cage['signedVolume'] < source['signedVolume']
        assert state['snapshot']['styled']['materials'] == ['paint']
        assert state['snapshot']['cage']['materials'] == ['paint']
        assert state['snapshot']['imported']['materials'] != ['paint'], 'source was mutated'
        volumes.append(cage['signedVolume'])
    assert volumes[1] > volumes[0], 'increased thickness did not increase strut volume'
    assert receipt['states'][1]['updated'] == ['cage'], 'upstream geometry was unnecessarily rebuilt'
    return {'verified': True, 'checks': ['sphere volume', 'geometry-preserving material assignment',
            'source material isolation', 'wireframe topology and thickness response', 'downstream-only invalidation']}


if __name__ == '__main__':
    print(json.dumps(check(sys.argv[1]), indent=2))
