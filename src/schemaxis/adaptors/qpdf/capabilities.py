"""Curated PDF page-assembly discovery."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'QPDF', 'purpose': 'Merge, reorder, repeat and rotate selected pages from captured PDFs into one new PDF, checked against the sources by fresh native observation.',
                            'keywords': ['PDF merge', 'merge PDF', 'combine PDF', 'combine PDF files', 'reorder pages', 'reorder PDF pages', 'extract pages', 'extract PDF pages', 'page assembly', 'QPDF']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['Configure QPDF 12.4.2 (--qpdf) and MuPDF 1.28.5 mutool (--mupdf) on POSIX; choose absolute bounded local unencrypted regular PDFs.',
                             'Name each source, then list output pages in order as source name, one-based physical page and optional clockwise quarter turn.',
                             'Bounded page assembly only: no forms, signatures, layers, tagged structure, annotations on selected pages, sanitising, editing or OCR.'],
            'references': ['docs/qpdf.md', 'src/schemaxis/adaptors/qpdf/readiness.json', 'examples/schemaxis/qpdf-to-mupdf.json', 'examples/schemaxis/qpdf-chain.json'],
            'operations': {'assemble': {
                'purpose': 'Build a new PDF from selected pages of named captured PDFs in a declared order, with repeats and relative quarter-turn rotation, and verify every output page against its source page.',
                'keywords': ['PDF merge', 'merge PDF', 'merge PDFs', 'combine PDFs', 'combine PDF files', 'reorder pages', 'reorder PDF pages', 'rearrange PDF pages', 'extract pages', 'extract PDF pages', 'repeat page', 'repeat PDF pages', 'rotate pages', 'rotate PDF pages', 'packet', 'handout', 'qpdf --pages'],
                'semantics': ['Output page order is the list order; a repeated page becomes an independent page and may carry its own rotation.',
                              'Rotation is relative to the page\'s effective rotation; MediaBox, CropBox, optional boxes and UserUnit are preserved and checked.',
                              'Document-level data (information, outlines, named destinations, open actions, labels) is discarded; unsupported features refuse.',
                              'Verification re-opens the captured sources and the published PDF with QPDF and MuPDF and requires exact 36 dpi raster, text and geometry agreement.'],
                'examples': [{'reference': 'examples/schemaxis/qpdf-assemble.json', 'purpose': 'Reorder pages from two PDFs and repeat one page.'},
                             {'reference': 'examples/schemaxis/qpdf-assemble-variant.json', 'purpose': 'Reverse the order and turn repeated pages differently.'}]}}}
