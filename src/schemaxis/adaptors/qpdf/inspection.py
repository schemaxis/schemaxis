"""Bounded page-assembly admission over QPDF's JSON; host-only, no native imports.

This is not a PDF parser and not a sanitiser. QPDF supplies the object structure; this
module applies typed checks to the selected pages and their effective resources, and to
the catalogue, using explicit allow-lists. Field names, /Type, /Subtype and /S values and
the arbitrary names of resource maps are kept distinct. Sibling pages are never read.
"""
import json
import math
import re

from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail

REF = re.compile(r'^(\d+) (\d+) R$')

MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_OBJECTS = 200000        # entries in qpdf's object table, and objects reachable from one selection
MAX_SOURCE_PAGES = 500
MAX_ANCESTRY = 32           # page-tree depth above a selected page
MAX_REF_DEPTH = 32          # reference dereferences along one resource path
MAX_REF_CHAIN = 16          # indirect objects that are only references
COORDINATE = 1e7            # finite raw coordinate bound, points
MAX_SIDE_POINTS = 8192.0    # physical (UserUnit-scaled) crop side
USER_UNIT_MAX = 75000.0
MAX_SIDE_PIXELS = 4096
MAX_TOTAL_PIXELS = 16777216
DPI = 36

PAGE_KEYS = {'/Type', '/Parent', '/Resources', '/Contents', '/MediaBox', '/CropBox', '/Rotate',
             '/BleedBox', '/TrimBox', '/ArtBox', '/UserUnit', '/Annots'}
ANCESTOR_KEYS = {'/Type', '/Parent', '/Kids', '/Count', '/MediaBox', '/CropBox', '/Rotate', '/Resources'}
CATALOGUE_STRUCTURAL = {'/Type', '/Pages', '/Version'}
CATALOGUE_DISCARDED = {'/Metadata', '/Outlines', '/Names', '/Dests', '/OpenAction', '/AA', '/PageLayout',
                       '/PageMode', '/ViewerPreferences', '/Lang', '/PageLabels'}
CATALOGUE_REFUSED = {'/AcroForm', '/Perms', '/OCProperties', '/OutputIntents', '/StructTreeRoot',
                     '/MarkInfo', '/Threads', '/AF', '/Extensions'}
RESOURCE_KEYS = {'/ProcSet', '/Font', '/XObject', '/ColorSpace', '/Pattern', '/Shading', '/ExtGState', '/Properties'}
# Keys of these maps are arbitrary resource/glyph names, never field names.
NAME_MAPS = {'/Font', '/XObject', '/ColorSpace', '/Pattern', '/Shading', '/ExtGState', '/Properties',
             '/CharProcs', '/Colorants'}
DENIED_KEYS = {'/JS', '/JavaScript', '/AA', '/OC', '/EF', '/AF'}
DENIED_STREAM_KEYS = {'/F', '/FFilter', '/FDecodeParms', '/Ref', '/OPI'}   # external-file and external-reference stream entries (reference XObjects, OPI)
DENIED_ACTIONS = {'/Launch', '/JavaScript', '/URI', '/SubmitForm', '/ImportData', '/GoToR', '/GoToE',
                  '/Rendition', '/Movie', '/Sound', '/Thread', '/Hide', '/Named', '/SetOCGState',
                  '/Trans', '/GoTo3DView', '/RichMediaExecute', '/ResetForm'}
DENIED_TYPES = {'/Filespec', '/EmbeddedFile', '/OCG', '/OCMD', '/Action', '/Rendition', '/Annot',
                '/RichMediaContent', '/3D'}
DENIED_SUBTYPES = {'/RichMedia', '/3D', '/Movie', '/Sound', '/Screen', '/FileAttachment', '/Widget', '/Link', '/Sig'}
TRAILER_KEYS = {'/Root', '/ID', '/Size'}
XREF_STREAM_KEYS = {'/Type', '/W', '/Index', '/Filter', '/DecodeParms', '/Length'}


def parse(data, what, code='PDF_STRUCTURE_UNSUPPORTED'):
    """Bounded JSON parse with the same limits for sources and the final PDF."""
    if len(data) > MAX_JSON_BYTES:
        fail('PDF_STRUCTURE_LIMIT', what + ': qpdf JSON exceeds %d bytes' % MAX_JSON_BYTES)
    try:
        value = json.loads(data)
        objects = value['qpdf'][1]
        if (value.get('version') != 2 or not isinstance(objects, dict) or not isinstance(value['pages'], list)
                or not isinstance(objects['trailer']['value'], dict) or not isinstance(value['encrypt'], dict)):
            raise ValueError('unexpected qpdf JSON shape')
    except RecursionError:
        fail('PDF_STRUCTURE_LIMIT', what + ': qpdf JSON nesting exceeds the parser bound')
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError) as error:
        fail(code, what + ': malformed qpdf JSON (' + str(error)[:80] + ')')
    if len(objects) > MAX_OBJECTS:
        fail('PDF_STRUCTURE_LIMIT', what + ': %d objects exceed the %d object bound' % (len(objects), MAX_OBJECTS))
    return value


def guarded(function):
    """Malformed native structure becomes a declared fault, never a leaked Python exception."""
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError) as error:
            fail('PDF_STRUCTURE_UNSUPPORTED', 'unexpected PDF structure: ' + type(error).__name__ + ' ' + str(error)[:80])
    wrapper.__name__ = function.__name__
    return wrapper


class Document:
    def __init__(self, parsed, label):
        self.parsed, self.label = parsed, label
        self.objects = parsed['qpdf'][1]
        self.trailer = self.objects['trailer']['value']

    def where(self, text=''):
        return self.label + (': ' + text if text else '')

    def resolve(self, value):
        """Follow indirect references (bounded); an absent object resolves to None."""
        for _ in range(MAX_REF_CHAIN + 1):
            if not (isinstance(value, str) and REF.match(value)):
                return value
            item = self.objects.get('obj:' + value)
            if item is None:
                return None
            value = item['stream']['dict'] if 'stream' in item else item.get('value')
        fail('PDF_STRUCTURE_LIMIT', self.where('indirect reference chain longer than %d' % MAX_REF_CHAIN))

    def number(self, value, name, code='PDF_GEOMETRY_UNSUPPORTED'):
        value = self.resolve(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > COORDINATE:
            fail(code, self.where(name + ' needs finite numbers within +/-%g' % COORDINATE))
        return value

    def box(self, value, name):
        value = self.resolve(value)
        if value is None:
            return None
        if not isinstance(value, list) or len(value) != 4:
            fail('PDF_GEOMETRY_UNSUPPORTED', self.where(name + ' needs an array of four numbers'))
        x0, y0, x1, y1 = (self.number(item, name) for item in value)
        if not (x0 < x1 and y0 < y1):
            fail('PDF_GEOMETRY_UNSUPPORTED', self.where(name + ' needs an ordered non-empty rectangle (x0<x1, y0<y1)'))
        return [x0, y0, x1, y1]

    def node(self, ref):
        value = self.resolve(ref)
        if not isinstance(value, dict):
            fail('PDF_PAGE_TREE', self.where('page-tree node is not a dictionary'))
        return value

    def ancestry(self, ref):
        """Page, parent, grandparent, ...; never /Kids; bounded and cycle-checked."""
        chain, seen, current = [], set(), ref
        while current is not None:
            if current in seen:
                fail('PDF_PAGE_TREE', self.where('page-tree ancestor cycle'))
            seen.add(current)
            if len(chain) >= MAX_ANCESTRY:
                fail('PDF_PAGE_TREE', self.where('page tree deeper than %d levels' % MAX_ANCESTRY))
            node = self.node(current)
            chain.append((current, node))
            parent = node.get('/Parent')
            current = parent if isinstance(parent, str) and REF.match(parent) else None
        return chain

    @staticmethod
    def inherited(chain, key):
        """Only MediaBox, CropBox, Resources and Rotate inherit."""
        for _, node in chain:
            if node.get(key) is not None:
                return node[key]
        return None

    @staticmethod
    def inside(inner, outer):
        return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def page_references(document):
    refs = [entry['object'] for entry in document.parsed['pages']]
    if not all(isinstance(ref, str) and REF.match(ref) for ref in refs):
        fail('PDF_STRUCTURE_UNSUPPORTED', document.where('qpdf page list is malformed'))
    return refs


class Budget:
    def __init__(self):
        self.remaining, self.seen = MAX_OBJECTS, set()


def walk(document, value, budget, where, depth=0):
    """Contextual walk: field names as names, /Type /Subtype /S as values, name-map keys skipped."""
    if depth > MAX_REF_DEPTH:
        fail('PDF_STRUCTURE_LIMIT', document.where('reference chain deeper than %d at %s' % (MAX_REF_DEPTH, where)))
    if isinstance(value, str) and REF.match(value):
        if value in budget.seen:
            return
        budget.seen.add(value)
        budget.remaining -= 1
        if budget.remaining < 0:
            fail('PDF_STRUCTURE_LIMIT', document.where('more than %d objects reachable from the selection' % MAX_OBJECTS))
        item = document.objects.get('obj:' + value)
        if item is None:
            return
        if 'stream' in item:
            stream_check(document, item['stream']['dict'], where, value)
            return walk(document, item['stream']['dict'], budget, where, depth + 1)
        return walk(document, item.get('value'), budget, where, depth + 1)
    if isinstance(value, list):
        for item in value:
            walk(document, item, budget, where, depth)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key in ('/Parent', '/P', '/Kids'):
            continue                                        # back pointers and siblings are never followed
        if key in NAME_MAPS:
            members = document.resolve(item)
            if isinstance(members, dict):
                for member in members.values():
                    walk(document, member, budget, where + ' ' + key, depth)
            else:
                walk(document, item, budget, where, depth)
            continue
        if key in DENIED_KEYS:
            fail('PDF_FEATURE_UNSUPPORTED', document.where('%s entry at %s is not supported' % (key, where)))
        if key == '/Type' and item in DENIED_TYPES:
            fail('PDF_FEATURE_UNSUPPORTED', document.where('/Type %s at %s is not supported' % (item, where)))
        if key == '/Subtype' and item in DENIED_SUBTYPES:
            fail('PDF_FEATURE_UNSUPPORTED', document.where('/Subtype %s at %s is not supported' % (item, where)))
        if key == '/S' and item in DENIED_ACTIONS:
            fail('PDF_FEATURE_UNSUPPORTED', document.where('action /S %s at %s is not supported' % (item, where)))
        walk(document, item, budget, where, depth)


def stream_check(document, dictionary, where, ref):
    bad = sorted(set(dictionary) & DENIED_STREAM_KEYS)
    if bad:
        fail('PDF_FEATURE_UNSUPPORTED', document.where('external-file stream entries %s at %s %s' % (','.join(bad), where, ref)))


def scan_resources(document, resources, budget):
    resources = document.resolve(resources)
    if resources is None:
        return
    if not isinstance(resources, dict):
        fail('PDF_RESOURCE_UNSUPPORTED', document.where('/Resources must be a dictionary'))
    unknown = sorted(set(resources) - RESOURCE_KEYS)
    if unknown:
        fail('PDF_RESOURCE_UNSUPPORTED', document.where('resource categories ' + ','.join(unknown) + ' are not supported'))
    walk(document, resources, budget, 'Resources')


def page_geometry(document, ref, budget):
    """Selected-page envelope, ancestor envelope, typed geometry and contextual resource scan."""
    chain = document.ancestry(ref)
    page = chain[0][1]
    unknown = sorted(set(page) - PAGE_KEYS)
    if unknown:
        fail('PDF_PAGE_FEATURE_UNSUPPORTED', document.where('page keys ' + ','.join(unknown) + ' are not supported'))
    if '/Annots' in page and document.resolve(page['/Annots']) not in (None, []):
        fail('PDF_ANNOTATIONS_UNSUPPORTED', document.where('the page has annotations (links, notes, widgets); choose pages without them'))
    for parent_ref, node in chain[1:]:
        bad = sorted(set(node) - ANCESTOR_KEYS)
        if bad:
            fail('PDF_PAGE_FEATURE_UNSUPPORTED', document.where('page-tree node %s keys %s are not supported '
                 '(only MediaBox, CropBox, Resources and Rotate inherit)' % (parent_ref, ','.join(bad))))
    media = document.box(document.inherited(chain, '/MediaBox'), 'MediaBox')
    if media is None:
        parent = chain[-1][1].get('/Parent')
        direct = parent is not None and not (isinstance(parent, str) and REF.match(parent))
        fail('PDF_GEOMETRY_UNSUPPORTED', document.where('no MediaBox in the page ancestry' + (
            '; a /Parent that is a direct object rather than an indirect reference is unsupported, so inherited values cannot be resolved' if direct else '')))
    crop = document.box(document.inherited(chain, '/CropBox'), 'CropBox')
    if crop is not None and not document.inside(crop, media):
        fail('PDF_GEOMETRY_UNSUPPORTED', document.where('CropBox must lie inside MediaBox'))
    effective = crop or media
    optional = {}
    for key in ('/BleedBox', '/TrimBox', '/ArtBox'):          # page-local only
        box = document.box(page.get(key), key[1:])
        if box is not None and not document.inside(box, media):
            fail('PDF_GEOMETRY_UNSUPPORTED', document.where(key[1:] + ' must lie inside MediaBox'))
        optional[key[1:]] = box or effective
    rotate = document.resolve(document.inherited(chain, '/Rotate'))
    if rotate is None:
        rotate = 0
    if isinstance(rotate, bool) or not isinstance(rotate, int) or rotate % 90 or abs(rotate) > 36000:
        fail('PDF_GEOMETRY_UNSUPPORTED', document.where('Rotate must be an integer multiple of 90'))
    unit = 1
    if page.get('/UserUnit') is not None:                     # page-local; explicit 0/negative/string is invalid
        unit = document.resolve(page['/UserUnit'])
        if isinstance(unit, bool) or not isinstance(unit, (int, float)) or not math.isfinite(unit) or not 0 < unit <= USER_UNIT_MAX:
            fail('PDF_GEOMETRY_UNSUPPORTED', document.where('UserUnit must be a number in (0,%g]' % USER_UNIT_MAX))
    width, height = (effective[2] - effective[0]) * unit, (effective[3] - effective[1]) * unit
    if width > MAX_SIDE_POINTS or height > MAX_SIDE_POINTS:
        fail('PDF_GEOMETRY_LIMIT', document.where('physical page size %gx%g points exceeds %g points per side' % (width, height, MAX_SIDE_POINTS)))
    scan_resources(document, document.inherited(chain, '/Resources'), budget)
    contents = page.get('/Contents')
    for item in (document.resolve(contents) if isinstance(document.resolve(contents), list) else [contents]):
        if isinstance(item, str) and REF.match(item):
            entry = document.objects.get('obj:' + item)
            if entry is not None and 'stream' in entry:
                stream_check(document, entry['stream']['dict'], 'Contents', item)
    return {'mediaBox': media, 'effective': effective, 'userUnit': unit, 'rotate': rotate % 360,
            'optionalBoxes': optional, 'physical': [width, height]}


@guarded
def catalogue(document):
    """Document-level policy: known data is discarded as a recorded loss; anything else refuses."""
    root = document.resolve(document.trailer.get('/Root'))
    if not isinstance(root, dict):
        fail('PDF_STRUCTURE_UNSUPPORTED', document.where('missing document catalogue'))
    if document.trailer.get('/Encrypt') is not None or document.parsed['encrypt'].get('encrypted'):
        fail('ENCRYPTED_PDF', document.where('encrypted PDFs are unsupported; supply an authorized unencrypted copy'))
    refused = sorted(set(root) & CATALOGUE_REFUSED)
    if refused:
        fail('PDF_CATALOGUE_UNSUPPORTED', document.where('catalogue entries ' + ','.join(refused) + ' are not supported'))
    unknown = sorted(set(root) - CATALOGUE_STRUCTURAL - CATALOGUE_DISCARDED)
    if unknown:
        fail('PDF_CATALOGUE_UNSUPPORTED', document.where('unknown catalogue entries ' + ','.join(unknown)))
    return sorted(set(root) & CATALOGUE_DISCARDED)


@guarded
def admit_source(document, pages):
    """Admit one captured source for the selected one-based pages; returns {page: geometry}."""
    references = page_references(document)
    if len(references) > MAX_SOURCE_PAGES:
        fail('PDF_PAGE_LIMIT', document.where('%d pages exceed the %d page limit' % (len(references), MAX_SOURCE_PAGES)))
    for page in pages:
        if page > len(references):
            fail('PDF_PAGE_RANGE', document.where('page %d requested but the PDF has %d pages' % (page, len(references))))
    discarded = catalogue(document)
    budget = Budget()
    geometry = {page: page_geometry(document, references[page - 1], budget) for page in sorted(set(pages))}
    return {'pages': len(references), 'discarded': discarded, 'geometry': geometry}


def predicted_pixels(geometry, extra_rotate, dpi=DPI):
    """Origin-aligned integer pixmap size for a page turned by extra_rotate degrees."""
    width, height = geometry['physical']
    if (geometry['rotate'] + extra_rotate) % 360 in (90, 270):
        width, height = height, width
    scale = dpi / 72.0
    return math.ceil(width * scale - 0.001), math.ceil(height * scale - 0.001)


def pixel_budget(sizes):
    """Per-side and cumulative raster budgets over all output pages, repeats included."""
    total = 0
    for index, (width, height) in enumerate(sizes, 1):
        total += width * height
        if not (1 <= width <= MAX_SIDE_PIXELS and 1 <= height <= MAX_SIDE_PIXELS) or total > MAX_TOTAL_PIXELS:
            fail('PDF_PIXEL_LIMIT', 'output page %d would need a %dx%d raster (cumulative %d of %d pixels); select fewer or smaller pages'
                 % (index, width, height, total, MAX_TOTAL_PIXELS), '$.pages')
    return total


@guarded
def check_final(document, positions, sources, code='VERIFICATION_FAILED'):
    """Final-bytes envelope: catalogue, trailer, page-tree membership/order and per-page geometry.

    positions = [(name, page, rotate)]; sources[name]['geometry'][page] come from fresh source admission.
    """
    root = document.resolve(document.trailer.get('/Root'))
    if document.parsed['encrypt'].get('encrypted') or document.trailer.get('/Encrypt') is not None:
        fail(code, 'the published PDF is encrypted')
    allowed = set(TRAILER_KEYS)
    if document.trailer.get('/Type') == '/XRef':                 # an xref-stream dictionary is structural
        allowed |= XREF_STREAM_KEYS
    if set(document.trailer) - allowed:
        fail(code, 'the published PDF has unexpected trailer entries ' + ','.join(sorted(set(document.trailer) - allowed)))
    if not isinstance(root, dict) or set(root) != {'/Type', '/Pages'}:
        extra = sorted(set(root) - {'/Type', '/Pages'}) if isinstance(root, dict) else ['?']
        fail(code, 'the published PDF catalogue carries unexpected entries ' + ','.join(extra))
    references = page_references(document)
    if len(references) != len(positions):
        fail(code, 'the published PDF has %d pages; the request selects %d' % (len(references), len(positions)))
    if len(set(references)) != len(references):
        fail(code, 'the published page tree repeats a page object')
    budget = Budget()
    geometry = []
    for index, ((name, page, rotate), ref) in enumerate(zip(positions, references), 1):
        try:
            actual = page_geometry(document, ref, budget)
        except SchemaxisError as error:                          # an envelope breach in published bytes is a verification failure
            fail(code, 'output page %d: %s' % (index, error.fault.message))
        expected = sources[name]['geometry'][page]
        for field in ('mediaBox', 'effective', 'userUnit', 'optionalBoxes', 'physical'):
            if actual[field] != expected[field]:
                fail(code, 'output page %d: %s differs from captured source %s page %d' % (index, field, name, page))
        if actual['rotate'] != (expected['rotate'] + rotate) % 360:
            fail(code, 'output page %d: rotation %d differs from (%d + %d) mod 360' % (index, actual['rotate'], expected['rotate'], rotate))
        geometry.append(actual)
    return geometry
