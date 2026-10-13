#!/usr/bin/env python3
"""Qualify projected polygon centroids and reject unsupported native inputs."""
import argparse
import copy
import json
from pathlib import Path
from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors import registry
from schemaxis.configuration import locations
from schemaxis.core.faults import SchemaxisError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parents[1]
    fixture = json.loads((repository/'examples/schemaxis/qgis-parcel.geojson').read_text())
    document = json.loads((repository/'examples/schemaxis/qgis-centroids.json').read_text())
    report = {'verified': False, 'negative': {}}
    try:
        receipt = qualify('schemaxis.qgis/1', root/'native', native=True)
        assert receipt['verified'], receipt
        report['nativeReceipt'] = str(root/'native/qualification.json')
        for name, expected in [('geographic', 'centroid requires a projected CRS'),
                               ('points', 'centroid requires polygon')]:
            source = copy.deepcopy(fixture)
            if name == 'geographic':
                source['crs']['properties']['name'] = 'EPSG:4326'
            else:
                source['features'][0]['geometry'] = {'type': 'Point', 'coordinates': [5, 10]}
            path = root/(name+'.geojson')
            path.write_text(json.dumps(source))
            document['nodes'][0]['options']['file'] = str(path)
            try:
                registry.run(document, root/name, locations=locations(), timeout=60)
            except SchemaxisError as error:
                assert error.fault.code == 'NATIVE_EXECUTION_FAILED' and expected in error.fault.message, error
                report['negative'][name] = error.fault.to_dict()
            else:
                raise AssertionError('unsupported centroid input succeeded: '+name)
        report['verified'] = True
    finally:
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
