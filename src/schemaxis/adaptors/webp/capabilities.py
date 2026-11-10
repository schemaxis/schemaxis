"""Curated intent-level lossless and bounded lossy WebP publication, and WebP-to-PNG decode, discovery."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'WebP', 'purpose': 'Publish one verified PNG as a WebP (lossless for illustrations and transparent assets, with decoded pixels including invisible RGB under zero alpha proven identical; or lossy for opaque photograph-like images within an authored error and size budget), or decode one static WebP back to a PNG that reports and other tools accept.',
                            'keywords': ['WebP', 'lossless WebP', 'lossy WebP', 'libwebp', 'cwebp', 'dwebp', 'web image', 'transparent asset', 'PNG to WebP', 'photo', 'WebP to PNG']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['Absolute captured local non-interlaced 8-bit RGB/RGBA PNG, sRGB or untagged, within 2048 pixels per side and 1,048,576 pixels.',
                             'Configured libwebp 1.6 cwebp (--webp) and dwebp (--dwebp) to run the encode operations; decodeToPng and verification need only dwebp (SCHEMAXIS_DWEBP or a stored location) because no host WebP decoder exists.',
                             'decodeToPng needs one captured local static simple-format WebP (one VP8L or opaque VP8 chunk, at most 16 MiB, 2048 pixels per side and 1,048,576 pixels); animated, extended, ICC, EXIF and XMP files are refused.',
                             'encodeLossy needs every pixel opaque, an integer quality 0-100 and a maxMeanRGBError budget; no near-lossless, animated, resized, ICC or metadata-retaining output; no authored native flags.'],
            'references': ['docs/webp.md', 'src/schemaxis/adaptors/webp/readiness.json'],
            'operations': {'encodeLossless': {
                'purpose': 'Encode a bounded PNG as a lossless WebP (VP8L) for web pages, preserving every RGBA sample and re-decoding the published bytes with native dwebp to prove it.',
                'keywords': ['WebP', 'lossless', 'convert PNG to WebP', 'web publishing', 'transparent', 'alpha', 'exact', 'illustration', 'cwebp', 'libwebp'],
                'semantics': ['Pixels are exact, including RGB hidden under alpha 0 (cwebp -exact); RGB sources gain alpha 255; sRGB assumed, ICC refused.',
                              'Verification needs the configured native dwebp: there is no independent host WebP decoder, so the published bytes are re-decoded by libwebp itself.'],
                'examples': [{'reference': 'examples/schemaxis/webp-baseline.json', 'purpose': 'Publish a transparent RGBA swatch with invisible colour under zero alpha.'},
                             {'reference': 'examples/schemaxis/webp-variant.json', 'purpose': 'Publish a flat-colour illustration with a transparent margin that carries invisible colour.'}]},
                'encodeLossy': {
                'purpose': 'Encode an opaque PNG as a lossy WebP (VP8) for web pages with authored quality, mean-RGB-error and byte budgets; the published bytes are decoded again by native dwebp and refused if over budget.',
                'keywords': ['compress photo for web', 'WebP', 'lossy', 'photo', 'photograph', 'quality', 'smaller image', 'compress image', 'web image', 'opaque', 'size budget', 'cwebp', 'libwebp'],
                'semantics': ['Every pixel must have alpha 255; partial or zero alpha is refused (use encodeLossless).',
                              'quality is an explicit integer 0-100 (100 is not lossless); there is no automatic quality search and no compression guarantee.',
                              'The mean absolute error over all RGB samples is measured against a fresh trusted dwebp decode and compared exactly with maxMeanRGBError; it is not a perceptual score. A file above maxBytes, or an error above the budget, fails DELIVERABLE_NOT_MET.'],
                'examples': [{'reference': 'examples/schemaxis/webp-lossy-gradient.json', 'purpose': 'Publish an opaque gradient with a bounded error and size budget.'},
                             {'reference': 'examples/schemaxis/webp-lossy-chart.json', 'purpose': 'Publish a saturated colour chart, where lossy coding is larger and less accurate than lossless.'}]},
                'decodeToPng': {
                'purpose': 'Decode one captured static WebP to a canonical 8-bit RGB or RGBA PNG for reports and other tools, proving with a fresh native dwebp decode that every PNG sample equals the decoder output.',
                'keywords': ['decode WebP', 'WebP to PNG', 'convert WebP to PNG', 'export PNG from WebP', 'unpack WebP', 'WebP asset', 'report image', 'dwebp', 'libwebp', 'static WebP'],
                'semantics': ['Only a static simple-format WebP is accepted (one VP8L chunk, or one opaque VP8 chunk); animated, extended, ICC, EXIF and XMP files are refused before any native process runs.',
                              'Lossless input decodes exactly, including RGB hidden under alpha 0; a lossy WebP becomes the libwebp decoder output, not the original picture. Needs only dwebp, not cwebp.',
                              'The PNG has only IHDR, IDAT and IEND, is untagged (sRGB by convention) and is RGBA only when the VP8L alpha hint is set. Agreement is semantic with libwebp, not an independent WebP decoder, and does not authenticate the source.'],
                'examples': [{'reference': 'examples/schemaxis/webp-decode-lossless.json', 'purpose': 'Decode a 4x3 lossless WebP with partial alpha and hidden colour to an RGBA PNG.'},
                             {'reference': 'examples/schemaxis/webp-decode-lossy.json', 'purpose': 'Decode an opaque lossy WebP gradient to an RGB PNG.'}]}}}
