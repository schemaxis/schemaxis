"""Independent geometry checks for blender-showcase and the sphere bridge."""
import argparse
import json
import math
from pathlib import Path


def check(directory, bridge=False):
    receipt = json.loads((Path(directory) / 'verification.json').read_text())
    assert receipt['status'] == 'succeeded'
    if bridge:
        assert len(receipt['states']) == 1
        observed = receipt['states'][0]['observations']['imported']
        assert observed['points'] > 100
        assert math.isclose(observed['signedVolume'], 4*math.pi*2**3/3, rel_tol=.03)
        assert all(math.isclose(abs(b), 2, rel_tol=.01) for b in observed['bounds'])
        checks = ['imported sphere volume within 3 percent of analytic volume', 'radius-two world bounds']
    else:
        assert len(receipt['states']) == 2
        for state, size in zip(receipt['states'], [2, 3]):
            observations = state['observations']
            box, rounded = observations['box'], observations['rounded']
            assert box['points'] == 8 and box['cells'] == 6
            assert math.isclose(box['signedVolume'], size**3, rel_tol=1e-6)
            assert box['bounds'] == [-size/2, size/2]*3
            assert 0 < rounded['signedVolume'] < box['signedVolume']
            assert rounded['points'] > box['points']
            assert 'unusedPaint' not in state['effective']
            assert all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(
                observations['paint']['shaderColour'], state['effective']['paint']['colour']))
        checks = ['exact cube volumes 8 and 27', 'outward winding', 'evaluated bevel removes volume',
                  'synchronized shader colour', 'unused material pruned']
    return {'verified': True, 'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    parser.add_argument('--bridge', action='store_true')
    args = parser.parse_args()
    print(json.dumps(check(args.directory, args.bridge), indent=2))
