#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Hand-built PDF fixtures and a literal oracle for the QPDF route.

Nothing here uses QPDF, the adaptor, or source-to-output comparison: colours, positions, text
and geometry are known by construction. The oracle samples a native render of an output page and
checks it against those constants after applying the clockwise rotation.
"""
from pathlib import Path
import math
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/qpdf'
COLOURS = {'red': (255, 0, 0), 'green': (0, 255, 0), 'blue': (0, 0, 255), 'yellow': (255, 255, 0),
           'cyan': (0, 255, 255), 'magenta': (255, 0, 255)}
# Quadrants listed bottom-left, bottom-right, top-left, top-right in PDF user space (y up).
PALETTES = [('red', 'green', 'blue', 'yellow'), ('yellow', 'blue', 'red', 'green'),
            ('green', 'red', 'yellow', 'blue'), ('cyan', 'magenta', 'green', 'red')]
OPERATORS = {'red': '1 0 0', 'green': '0 1 0', 'blue': '0 0 1', 'yellow': '1 1 0', 'cyan': '0 1 1', 'magenta': '1 0 1'}

# name: (MediaBox or None to inherit, CropBox or None, own Rotate or None, UserUnit or None, palette, text)
COVER = [([0, 0, 595.276, 841.89], None, None, None, 3, b'Cover page')]
REPORT = [(None, None, None, None, 0, b'Report 1'),
          ([-20, -40, 160, 140], [0, -20, 144, 124], None, None, 1, b'Report 2 caf\xe9'),
          ([0, 0, 240, 160], None, None, None, 2, b'Report 3'),
          ([0, 0, 100, 150], None, 270, 2, 3, b'Report 4')]
# The report root supplies MediaBox [0 0 200 300]; its page-tree node supplies /Rotate 90 to pages 1-3 unless they override it.
REPORT_ROOT_MEDIA = [0, 0, 200, 300]
REPORT_INHERITED_ROTATE = 90
REPORT_OWN_ROTATE = {2: 0}      # page 3 overrides the inherited 90 with 0


def fmt(box):
    return '[' + ' '.join('%g' % v for v in box) + ']'


def stream(content):
    return b'<< /Length %d >>\nstream\n' % len(content) + content + b'endstream'


def page_content(crop, palette, text):
    x0, y0, x1, y1 = crop
    w, h = (x1 - x0) / 2, (y1 - y0) / 2
    names = PALETTES[palette]
    out = []
    for (name, (x, y)) in zip(names, ((x0, y0), (x0 + w, y0), (x0, y0 + h), (x0 + w, y0 + h))):
        out.append(('%s rg %g %g %g %g re f' % (OPERATORS[name], x, y, w, h)).encode())
    out.append(b'0 0 0 rg BT /F1 9 Tf %g %g Td (' % (x0 + 4, y1 - 12) + text + b') Tj ET')
    return b'\n'.join(out) + b'\n'


def token(value):
    """Lists format as PDF arrays; bytes are inserted verbatim so qualification can build malformed tokens on purpose."""
    return value if isinstance(value, bytes) else fmt(value).encode()


def document(pages, root_media=None, inherited_rotate=None, own_rotate=None, extra_catalogue=b'', extra_page=b'', extra_objects=(),
             resources=b'<< /Font << /F1 4 0 R >> >>', extra_root=b'', extra_node=b'', contents=None, page_extras=None, parent=b'3 0 R'):
    """Return PDF bytes. pages: tuples like COVER/REPORT (media/crop/rotate/unit may be raw bytes). Objects: 1 catalogue, 2 root, 3 node,
    4 font, 5.. pages and contents; extra_objects are numbered from 100 upward."""
    own_rotate = own_rotate or {}
    objects = {1: b'<< /Type /Catalog /Pages 2 0 R ' + extra_catalogue + b'>>'}
    root = b'<< /Type /Pages /Kids [3 0 R] /Count %d' % len(pages)
    if root_media:
        root += b' /MediaBox ' + token(root_media)
    objects[2] = root + b' ' + extra_root + b' >>'
    node = b'<< /Type /Pages /Parent 2 0 R /Kids [' + b' '.join(b'%d 0 R' % (5 + 2 * i) for i in range(len(pages))) + b'] /Count %d' % len(pages)
    if inherited_rotate is not None:
        node += b' /Rotate %d' % inherited_rotate
    objects[3] = node + b' ' + extra_node + b' >>'
    objects[4] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
    for index, (media, crop, rotate, unit, palette, text) in enumerate(pages):
        number = 5 + 2 * index
        body = b'<< /Type /Page /Parent ' + parent + b' /Resources ' + resources + b' /Contents %d 0 R' % (number + 1)
        if media:
            body += b' /MediaBox ' + token(media)
        if crop:
            body += b' /CropBox ' + token(crop)
        if rotate is not None:
            body += b' /Rotate ' + (rotate if isinstance(rotate, bytes) else b'%d' % rotate)
        elif index in own_rotate:
            body += b' /Rotate %d' % own_rotate[index]
        if unit:
            body += b' /UserUnit ' + (unit if isinstance(unit, bytes) else b'%g' % unit)
        objects[number] = body + b' ' + extra_page + b' ' + (page_extras or {}).get(index, b'') + b' >>'
        box = crop or media or root_media
        objects[number + 1] = stream(contents[index] if contents and index < len(contents) and contents[index] is not None
                                     else page_content(box if isinstance(box, list) else [0, 0, 200, 300], palette, text))
    for offset, body in enumerate(extra_objects):
        objects[100 + offset] = body
    data = bytearray(b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(data)
        data += b'%d 0 obj\n' % number + objects[number] + b'\nendobj\n'
    size = max(objects) + 1
    xref = len(data)
    data += b'xref\n0 %d\n0000000000 65535 f \n' % size
    for number in range(1, size):
        data += (b'%010d 00000 n \n' % offsets[number]) if number in offsets else b'0000000000 65535 f \n'
    data += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (size, xref)
    return bytes(data)


def cover():
    return document(COVER, root_media=None)


def report():
    return document(REPORT, root_media=REPORT_ROOT_MEDIA, inherited_rotate=REPORT_INHERITED_ROTATE, own_rotate=REPORT_OWN_ROTATE)


# ----------------------------------------------------------------- literal expectations
def page_spec(source, page):
    """Return (effective crop box, own/inherited rotation, user unit, palette, text) for a fixture page, from the constants above."""
    if source == 'cover':
        media, crop, rotate, unit, palette, text = COVER[page - 1]
        return crop or media, rotate or 0, unit or 1, palette, text
    media, crop, rotate, unit, palette, text = REPORT[page - 1]
    base = rotate if rotate is not None else REPORT_OWN_ROTATE.get(page - 1, REPORT_INHERITED_ROTATE if page <= 3 else 0)
    return crop or media or REPORT_ROOT_MEDIA, base, unit or 1, palette, text


def expected_page(source, page, rotate):
    """Literal oracle record: pixel size at 36 dpi, quadrant colours by display position (row-major from top-left), text."""
    crop, base, unit, palette, text = page_spec(source, page)
    turn = (base + rotate) % 360
    width, height = (crop[2] - crop[0]) * unit, (crop[3] - crop[1]) * unit
    if turn in (90, 270):
        width, height = height, width
    names = PALETTES[palette]
    grid = [[names[2], names[3]], [names[0], names[1]]]          # unrotated display: top row then bottom row
    for _ in range(turn // 90):                                   # clockwise quarter turn
        grid = [[grid[1][0], grid[0][0]], [grid[1][1], grid[0][1]]]
    return {'size': [math.ceil(width * 0.5 - 0.001), math.ceil(height * 0.5 - 0.001)],
            'quadrants': [grid[0][0], grid[0][1], grid[1][0], grid[1][1]], 'text': text.decode('cp1252')}


# ----------------------------------------------------------------- independent PNM decoding
def read_pnm(path):
    data = Path(path).read_bytes()
    magic, geometry, maximum, pixels = data.split(b'\n', 3)
    width, height = map(int, geometry.split())
    assert magic == b'P6' and maximum == b'255' and len(pixels) == width * height * 3
    return width, height, pixels


def sample(image, fx, fy):
    width, height, pixels = image
    x, y = int(width * fx), int(height * fy)
    return tuple(pixels[(y * width + x) * 3:(y * width + x) * 3 + 3])


def render(mutool, pdf, page, directory):
    """Render one page with the native CLI (a separate invocation from the adaptor's observers) to RGB PNM."""
    output = Path(directory) / ('literal-%s-%d.pnm' % (Path(pdf).stem, page))
    subprocess.run([str(mutool), 'draw', '-q', '-c', 'rgb', '-r', '36', '-o', str(output), str(pdf), str(page)], check=True, capture_output=True, timeout=60)
    return output


def check(mutool, pdf, expectations, directory):
    """Literal check of an assembled PDF: one (source, page, rotate) expectation per output page, in order."""
    report_ = []
    for index, (source, page, rotate) in enumerate(expectations, 1):
        want = expected_page(source, page, rotate)
        image = read_pnm(render(mutool, pdf, index, directory))
        assert [image[0], image[1]] == want['size'], (index, [image[0], image[1]], want['size'])
        got = [sample(image, fx, fy) for fy in (0.25, 0.75) for fx in (0.25, 0.75)]
        # Text sits in a thin band at the top edge of the unrotated page; sampling quadrant centres avoids it.
        assert got == [COLOURS[name] for name in want['quadrants']], (index, got, want['quadrants'])
        text = subprocess.run([str(mutool), 'draw', '-q', '-F', 'txt', '-o', '-', str(pdf), str(index)], check=True, capture_output=True, timeout=60).stdout.decode('utf-8', 'replace')
        assert want['text'] in text, (index, text, want['text'])
        report_.append({'output': index, 'source': source, 'sourcePage': page, 'rotate': rotate, 'pixels': want['size'], 'quadrants': want['quadrants'], 'text': want['text']})
    return report_


# ----------------------------------------------------------------- qualification variants (generated at run time, not committed)
def single(text=b'Neg', palette=0, **kwargs):
    """One literal page on a 200x300 root MediaBox; kwargs go to document()."""
    return document([(None, None, None, None, palette, text)], root_media=[0, 0, 200, 300], **kwargs)


def twin(colour):
    """Same page dictionary, geometry and content-stream bytes; only a Form XObject resource differs in colour."""
    body = b'%s rg 20 40 100 100 re f' % colour
    form = b'<< /Type /XObject /Subtype /Form /BBox [0 0 200 300] /Length %d >>\nstream\n%s\nendstream' % (len(body), body)
    return document([(None, None, None, None, 0, b'Twin')], root_media=[0, 0, 200, 300], extra_objects=[form],
                    resources=b'<< /Font << /F1 4 0 R >> /XObject << /Fm1 100 0 R >> >>',
                    contents=[b'/Fm1 Do\n0 g BT /F1 14 Tf 20 250 Td (TWIN) Tj ET\n'])


def mark(x):
    """Identical large content plus one 6 pt square at x: a small mark that a percentage tolerance could miss."""
    return document([(None, None, None, None, 0, b'Marks')], root_media=[0, 0, 200, 300],
                    contents=[page_content([0, 0, 200, 300], 0, b'Marks') + b'0 0 0 rg %d 200 6 6 re f\n' % x])


def digit(value):
    return single(b'Page 1%d' % value)


def cropvar(crop):
    return document([(None, crop, None, None, 0, b'Crop')], root_media=[0, 0, 200, 300])


def many(count):
    return document([(None, None, None, None, 0, b'Many')] * count, root_media=[0, 0, 200, 300])


def padded(size):
    """A valid one-page PDF of about size bytes: an unreferenced stream is written before the xref, so QPDF and MuPDF read it normally."""
    filler = b'<< /Length %d >>\nstream\n%s\nendstream' % (size, bytes(size))
    return single(b'Padded', extra_objects=[filler])


def form_with(entry):
    """A page whose resources reach a Form XObject carrying an external-reference entry."""
    form = b'<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] ' + entry + b' /Length 0 >>\nstream\n\nendstream'
    return single(resources=b'<< /Font << /F1 4 0 R >> /XObject << /Fm1 100 0 R >> >>', extra_objects=[form])


LINK = b'<< /Type /Annot /Subtype /Link /Rect [10 10 80 40] /Border [0 0 1] >>'
OCG = b'<< /Type /OCG /Name (Hidden) >>'
# name: (document bytes, expected fault code(s)). qpdf itself warns about several malformed geometry tokens, which is also a refusal.
NEGATIVES = {
    'catalogue-acroform': (single(extra_catalogue=b'/AcroForm << /Fields [] >> '), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'catalogue-signature': (single(extra_catalogue=b'/AcroForm << /Fields [100 0 R] /SigFlags 3 >> ',
                                   extra_objects=[b'<< /FT /Sig /T (sig1) /V << /Type /Sig /ByteRange [0 10 20 10] /Contents <00> >> >>']), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'catalogue-perms': (single(extra_catalogue=b'/Perms << >> '), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'catalogue-layers': (single(extra_catalogue=b'/OCProperties << /OCGs [100 0 R] /D << /OFF [100 0 R] >> >> ', extra_objects=[OCG]), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'catalogue-output-intents': (single(extra_catalogue=b'/OutputIntents [] '), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'catalogue-tagged': (single(extra_catalogue=b'/MarkInfo << /Marked true >> /StructTreeRoot << /Type /StructTreeRoot >> '), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'catalogue-threads': (single(extra_catalogue=b'/Threads [] '), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'catalogue-unknown': (single(extra_catalogue=b'/Foo 1 '), {'PDF_CATALOGUE_UNSUPPORTED'}),
    'page-javascript-action': (single(extra_page=b'/AA << /O << /S /JavaScript /JS (app.alert\\(1\\)) >> >>'), {'PDF_PAGE_FEATURE_UNSUPPORTED'}),
    'page-structure-parents': (single(extra_page=b'/StructParents 0'), {'PDF_PAGE_FEATURE_UNSUPPORTED'}),
    'page-transition': (single(extra_page=b'/Trans << /S /Fade >> /Dur 3'), {'PDF_PAGE_FEATURE_UNSUPPORTED'}),
    'page-link-annotation': (single(extra_page=b'/Annots [100 0 R]', extra_objects=[LINK]), {'PDF_ANNOTATIONS_UNSUPPORTED'}),
    'page-malformed-annots': (single(extra_page=b'/Annots (x)'), {'PDF_REPAIRED', 'PDF_ANNOTATIONS_UNSUPPORTED'}),
    'resource-optional-content': (single(resources=b'<< /Properties << /oc1 100 0 R >> >>', extra_objects=[OCG]), {'PDF_FEATURE_UNSUPPORTED'}),
    'resource-launch-action': (single(resources=b'<< /Properties << /x << /S /Launch /F (calc.exe) >> >> >>'), {'PDF_FEATURE_UNSUPPORTED'}),
    'resource-uri-action': (single(resources=b'<< /ExtGState << /G << /S /URI /URI (http://x.invalid) >> >> >>'), {'PDF_FEATURE_UNSUPPORTED'}),
    'resource-filespec': (single(resources=b'<< /Properties << /x << /Type /Filespec /F (a.txt) >> >> >>'), {'PDF_FEATURE_UNSUPPORTED'}),
    'resource-javascript-key': (single(resources=b'<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /JS (1) >> >> >>'), {'PDF_FEATURE_UNSUPPORTED'}),
    'resource-reference-xobject': (form_with(b'/Ref << /F (other.pdf) /Page 1 >>'), {'PDF_FEATURE_UNSUPPORTED'}),
    'resource-opi': (form_with(b'/OPI << /2.0 << /Type /OPI /Version 2.0 /F (external.eps) >> >>'), {'PDF_FEATURE_UNSUPPORTED'}),
    'page-transparency-group': (single(extra_page=b'/Group << /S /Transparency /CS /DeviceRGB >>'), {'PDF_PAGE_FEATURE_UNSUPPORTED'}),
    'geometry-direct-object-parent': (document([(None, None, None, None, 0, b'G')], root_media=[0, 0, 200, 300],
                                               parent=b'<< /Type /Pages /Kids [] /Count 0 /MediaBox [0 0 200 300] >>'),
                                      {'PDF_GEOMETRY_UNSUPPORTED', 'PDF_REPAIRED', 'PDF_PAGE_TREE'}),
    'resource-unknown-category': (single(resources=b'<< /Font << /F1 4 0 R >> /Foo 1 >>'), {'PDF_RESOURCE_UNSUPPORTED'}),
    'geometry-userunit-zero': (document([(None, None, None, b'0', 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-userunit-negative': (document([(None, None, None, b'-2', 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-userunit-string': (document([(None, None, None, b'(2)', 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-userunit-huge-physical': (document([(None, None, None, b'75000', 0, b'G')], root_media=[0, 0, 8000, 8000]), {'PDF_GEOMETRY_LIMIT'}),
    'geometry-physical-9000-points': (document([(None, None, None, None, 0, b'G')], root_media=[0, 0, 9000, 100]), {'PDF_GEOMETRY_LIMIT'}),
    'geometry-rotate-45': (document([(None, None, b'45', None, 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-rotate-real': (document([(None, None, b'90.0', None, 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-rotate-string': (document([(None, None, b'(90)', None, 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-reversed-mediabox': (document([(None, None, None, None, 0, b'G')], root_media=[200, 300, 0, 0]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-empty-mediabox': (document([(None, None, None, None, 0, b'G')], root_media=[0, 0, 0, 0]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-cropbox-outside': (document([(None, [-50, -50, 250, 350], None, None, 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-cropbox-disjoint': (document([(None, [500, 500, 600, 600], None, None, 0, b'G')], root_media=[0, 0, 200, 300]), {'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-parent-only-userunit': (single(extra_root=b'/UserUnit 2'), {'PDF_PAGE_FEATURE_UNSUPPORTED'}),
    'geometry-parent-only-trimbox': (single(extra_node=b'/TrimBox [1 1 100 100]'), {'PDF_PAGE_FEATURE_UNSUPPORTED'}),
    'geometry-mediabox-name': (document([(None, None, None, None, 0, b'G')], root_media=b'/Letter'), {'PDF_REPAIRED', 'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-mediabox-three-numbers': (document([(None, None, None, None, 0, b'G')], root_media=b'[0 0 200]'), {'PDF_REPAIRED', 'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-mediabox-missing': (document([(None, None, None, None, 0, b'G')], root_media=None), {'PDF_REPAIRED', 'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-mediabox-huge-coordinate': (document([(None, None, None, None, 0, b'G')], root_media=b'[0 0 1e30 1e30]'), {'PDF_REPAIRED', 'PDF_GEOMETRY_UNSUPPORTED'}),
    'geometry-mediabox-integer-overflow': (document([(None, None, None, None, 0, b'G')], root_media=b'[0 0 99999999999999999999 300]'), {'INVALID_PDF_SOURCE', 'PDF_REPAIRED'}),
}
# Admitted by the host (its bottom-up and QPDF's top-down readings of the page tree agree on what it can see) yet refused by the fresh observation after
# assembly: the readers disagree. name: (document bytes, fragment of the refusal message). A failed run may leave assembled.pdf but never a receipt.
POST_ASSEMBLY = {
    'indirect-null-rotate-with-inherited-rotation': (document([(None, None, b'100 0 R', None, 0, b'G')], root_media=[0, 0, 200, 300], inherited_rotate=90, extra_objects=[b'null']),
                                                     'disagree on the source rotation'),
    'parent-off-the-kids-path': (document([(None, None, None, None, 0, b'G')], root_media=[0, 0, 200, 300], parent=b'100 0 R',
                                          extra_objects=[b'<< /Type /Pages /MediaBox [0 0 100 100] /Kids [] /Count 0 >>']), 'differs from captured source'),
}
# Accepted although they look dangerous or rich: ordinary names, discarded document data, an unselected prohibited sibling.
POSITIVES = {
    'decoy-names': document([(None, None, None, None, 0, b'Decoy')], root_media=[0, 0, 200, 300],
                            resources=b'<< /Font << /JS 4 0 R /Launch 4 0 R /AA 4 0 R /OC 4 0 R /EF 4 0 R >> >>',
                            contents=[b'0 g BT /JS 12 Tf 20 100 Td (Launch JavaScript URI) Tj ET\n']),
    'decoy-reference-names': single(resources=b'<< /Font << /F1 4 0 R >> /XObject << /Ref 100 0 R /OPI 100 0 R >> >>',
                                    extra_objects=[b'<< /Type /XObject /Subtype /Form /BBox [0 0 10 10] /Length 0 >>\nstream\n\nendstream']),
    'discarded-document-data': single(extra_catalogue=b'/Outlines << /Type /Outlines /Count 0 >> /PageLabels << /Nums [0 << /S /D >>] >> /Names << >> /OpenAction [5 0 R /Fit] '
                                      b'/PageMode /UseOutlines /ViewerPreferences << /HideToolbar true >> /Lang (en) /PageLayout /SinglePage '),
}


def sibling_prohibited():
    """Two pages; page 2 carries a page-level JavaScript action. Selecting only page 1 is accepted, selecting page 2 refuses."""
    return document([(None, None, None, None, 0, b'Clean'), (None, None, None, None, 1, b'Dirty')], root_media=[0, 0, 200, 300],
                    page_extras={1: b'/AA << /O << /S /JavaScript /JS (1) >> >>'})


def write_fixtures():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / 'cover.pdf').write_bytes(cover())
    (FIXTURES / 'report.pdf').write_bytes(report())


if __name__ == '__main__':
    write_fixtures()
    print('wrote', FIXTURES)
