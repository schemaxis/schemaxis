"""Curated offline scanned-page OCR discovery without native imports."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'Tesseract', 'purpose': 'Recognize the text of one local scanned-page PNG with a pinned English LSTM model, an explicit page segmentation and a bounded host-checked result: machine-draft text, word boxes in source pixels with uncalibrated confidence, and an inspectable summary that can retain a declared MuPDF page origin. Output is a draft for human review, not certified text.',
                            'keywords': ['OCR', 'optical character recognition', 'scanned page', 'scanned page OCR', 'Tesseract', 'recognize text in image', 'word boxes', 'machine draft', 'scanned PDF page', 'page image to text']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['Use an absolute local opaque 8-bit RGB non-interlaced PNG without alpha, at most 16MiB, 4096 pixels per side and 4,194,304 pixels; a MuPDF page PNG is accepted as an image artifact.',
                             'Use an absolute local English LSTM traineddata file (at most 64MiB) and its lowercase SHA-256; nothing is downloaded and no global tessdata, TESSDATA_PREFIX or configuration file is used.',
                             'Choose pageSegmentation explicitly: uniform-block for a multi-line block of text or single-line for exactly one line; a wrong choice can yield no words (OCR_NO_TEXT) or wrong text.',
                             'Configure Tesseract 5.5.3 (--tesseract or SCHEMAXIS_TESSERACT). Serial CPU only; no authored native flags, other languages, handwriting or layout analysis.',
                             'Confidence is the recogniser\'s uncalibrated 0-100 score; text is a machine draft. Origin is only retained from a declared MuPDF review summary whose page entry matches the pixels; a pixel-only image has no page identity.'],
            'references': ['docs/tesseract.md', 'src/schemaxis/adaptors/tesseract/readiness.json'],
            'operations': {OPERATION: {
                'purpose': 'Recognize one bounded scanned-page PNG with a pinned English LSTM model into checked machine-draft text, word boxes with confidence and an inspectable summary for human review.',
                'keywords': ['OCR', 'optical character recognition', 'scanned page', 'scanned page OCR', 'scan to text', 'recognize text in image', 'image to text', 'word boxes', 'word confidence', 'machine draft', 'Tesseract', 'page segmentation', 'TSV', 'scanned PDF page', 'page image to text'],
                'semantics': ['The page record and every word box are in source-image pixels with a top-left origin; the TSV is parsed by a strict independent reader (header, hierarchy, containment, confidence text) and the native text must agree with it.',
                              'Structure, hashes and text/TSV agreement do not certify that the text is what the page says; word confidence is uncalibrated; review output against the page image.',
                              'Page segmentation is explicit: uniform-block (--psm 6) or single-line (--psm 7). A mismatched choice can yield no words (refused as OCR_NO_TEXT rather than published empty; observed on the qualification fixture) or wrong text.',
                              'A MuPDF page PNG can be passed as a workflow artifact. Page identity is retained only when a declared MuPDF review summary entry matches the image pixels; otherwise the origin is recorded as unknown. Pandoc or other OCR-block ingestion is not offered.'],
                'examples': [{'reference': 'examples/schemaxis/tesseract-baseline.json', 'purpose': 'Recognize a two-line synthetic page with uniform-block segmentation at a declared 200 dpi.'},
                             {'reference': 'examples/schemaxis/tesseract-variant.json', 'purpose': 'Recognize a page whose second line has changed words.'},
                             {'reference': 'examples/schemaxis/tesseract-single-line.json', 'purpose': 'Recognize a one-line image with explicit single-line segmentation.'}]}}}


OPERATION = 'recognizePage'
