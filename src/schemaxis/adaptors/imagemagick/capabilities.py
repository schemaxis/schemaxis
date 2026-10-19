"""Curated intent-level PNG preparation discovery."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'ImageMagick','purpose':'Prepare exact raster PNG details and indexed contact sheets with explicit encoded sRGB and alpha policies.','keywords':['PNG','raster preparation','contact sheet','crop','nearest neighbour','quarter turn','alpha']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':['Absolute captured local RGB/RGBA8 PNG; declared sRGB or explicit assume-srgb policy.','No arbitrary options, formats, delegates, scripts, smoothing or colour conversion.'],
        'references':['docs/imagemagick.md','src/schemaxis/adaptors/imagemagick/readiness.json'],
        'operations':{'raster':{'purpose':'Crop raster PNG details, enlarge with nearest neighbour pixel replication, rotate quarter turns, preserve or flatten alpha and optionally assemble an indexed contact sheet.',
            'keywords':['crop','contact sheet','nearest neighbour','pixel art','raster','PNG','quarter turn','alpha','magnify','ImageMagick'],
            'semantics':['Integer top-left crop, magnification 1–8, clockwise 0–3 quarter turns, exact RGBA8 sample verification.','Flatten blends encoded sRGB samples with explicit RGB background; contact sheet has JSON index metadata and no visual text labels.'],
            'examples':[{'reference':'examples/schemaxis/imagemagick-baseline.json','purpose':'Enlarge a selected PNG detail without interpolation.'},{'reference':'examples/schemaxis/imagemagick-sheet.json','purpose':'Prepare two comparable views and publish indexed sheet metadata.'}]}}}
