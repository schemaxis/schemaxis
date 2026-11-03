# Copyright (C) 2026 David L F Gaden
"""Independent numerical checks for the showcase-acceptance.json native run."""
import argparse
import json
import math
from pathlib import Path


def check(directory):
    receipt = json.loads((Path(directory) / 'verification.json').read_text())
    if receipt['status'] != 'succeeded':
        raise AssertionError('native execution did not succeed')
    states, artifacts = receipt['states'], receipt['artifacts']
    assert len(states) == 24
    assert sum(a['identity']['kind'] == 'geometry' for a in artifacts) == 24
    assert sum(a['identity']['kind'] == 'image' for a in artifacts) == 576
    for index, state in enumerate(states):
        synchronized, independent = index % 8, index // 8
        values = state['effective']
        assert 'unused' not in values
        assert math.isclose(values['sphere']['radius'], 1 + 2*synchronized/7, abs_tol=1e-12)
        assert math.isclose(values['other']['radius'], 2 + 2*synchronized/7, abs_tol=1e-12)
        assert math.isclose(values['sphere']['centre'][0], 2*synchronized/7, abs_tol=1e-12)
        z = independent / 4
        assert math.isclose(values['cut']['origin'][2], z, abs_tol=1e-7)
        assert all(math.isclose(bound, z, abs_tol=1e-7) for bound in state['observations']['cut']['bounds'][4:6])
        assert state['proxyIds'] == states[0]['proxyIds']
    assert all(event['node'] != 'unused' for event in receipt['events'])
    return {'verified': True, 'checks': ['24 Cartesian geometry states', '576 camera/appearance images',
        'three synchronized members', 'requested slice planes', 'native object identity reuse', 'unused analytic pruned']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    print(json.dumps(check(parser.parse_args().directory), indent=2))
