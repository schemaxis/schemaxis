"""Curated passive PDF review discovery."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'MuPDF','purpose':'Review captured PDF pages as ordered raster previews, extracted text and crop/rotation metadata.','keywords':['PDF preview','page review','rasterize','archival preview','MuPDF']},
      'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
      'requirements':['Configure MuPDF 1.28.5 mutool on POSIX; choose an absolute bounded local unencrypted regular PDF.',
        'Declare distinct one-based pages in output order; fit raster dimensions and combined pixel budget.',
        'Passive rendering/extraction only: no authored scripts, PDF actions, URL fetching, general editing or OCR.'],
      'references':['docs/mupdf.md','src/schemaxis/adaptors/mupdf/readiness.json'],
      'operations':{'review':{'purpose':'Create an ordered PDF preview with page PNGs, extracted UTF-8 text and effective crop/rotation metadata for archival review.',
        'keywords':['PDF preview','rasterize','page review','page order','rotate','DPI','PNG','text extraction','CropBox','MediaBox','mutool'],
        'semantics':['Preserve native effective CropBox/inherited PDF rotation before the additional clockwise output quarter turn.',
          'Capture PDF bytes before execution; compare all PNG pixels and extracted text against fresh native source reopening.',
          'Literal fixture geometry/colours/text are independently checked; arbitrary PDF text reading order and Unicode are not guaranteed.'],
        'examples':[{'reference':'examples/schemaxis/mupdf-review.json','purpose':'Review a nontrivial page order at72dpi.'},
          {'reference':'examples/schemaxis/mupdf-review-variant.json','purpose':'Double density, reverse order and turn previews clockwise.'}]}}}
