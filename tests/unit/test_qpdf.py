"""Host-only QPDF contract, admission, geometry and verifier-mechanics checks; native acceptance is a separate tool."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.qpdf import adaptor, inspection
from schemaxis.adaptors.qpdf.native_source import source as observer_source
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation, execution_deadline

ROOT = Path(__file__).resolve().parents[2]
MEDIA = [0, 0, 200, 300]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def code_of(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.code
    raise AssertionError('accepted')


def synthetic(pages, root='/MediaBox', mid=None, catalogue=None, trailer=None, encrypted=False, objects=None, annots=None):
    """Return qpdf-JSON-shaped bytes. pages: list of page-dict bodies; root: dict (or the default MediaBox) for the Pages root."""
    root = {'/MediaBox': MEDIA} if root == '/MediaBox' else (root or {})
    refs = ['%d 0 R' % (10 + i) for i in range(len(pages))]
    holder = '3 0 R' if mid is not None else '2 0 R'
    table = {'trailer': {'value': {'/Root': '1 0 R', '/Size': 200, **(trailer or {})}},
             'obj:1 0 R': {'value': {'/Type': '/Catalog', '/Pages': '2 0 R', **(catalogue or {})}},
             'obj:2 0 R': {'value': {'/Type': '/Pages', '/Kids': ['3 0 R'] if mid is not None else refs, '/Count': len(pages), **root}}}
    if mid is not None:
        table['obj:3 0 R'] = {'value': {'/Type': '/Pages', '/Parent': '2 0 R', '/Kids': refs, '/Count': len(pages), **mid}}
    for index, body in enumerate(pages):
        table['obj:%s' % refs[index]] = {'value': {'/Type': '/Page', '/Parent': holder, '/Contents': '%d 0 R' % (100 + index), **body}}
        table['obj:%d 0 R' % (100 + index)] = {'stream': {'dict': {'/Length': 1}}}
    table.update(objects or {})
    return json.dumps({'version': 2, 'parameters': {}, 'pages': [{'object': r} for r in refs], 'encrypt': {'encrypted': encrypted},
                       'qpdf': [{}, table]}).encode()


def document(*args, label='test', **kwargs):
    return inspection.Document(inspection.parse(synthetic(*args, **kwargs), label), label)


def admit(pages, selected=(1,), **kwargs):
    return inspection.admit_source(document(pages, **kwargs), selected)


class QpdfPlan(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / 'examples/schemaxis/qpdf-assemble.json').read_text())

    def fault(self, document, code, location=None):
        with self.assertRaises(SchemaxisError) as raised:
            adaptor._native_plan(document)
        self.assertEqual(raised.exception.fault.code, code)
        if location:
            self.assertEqual(raised.exception.fault.location, location)

    def mutated(self, change):
        value = copy.deepcopy(self.document)
        change(value)
        return value

    def test_deterministic_immutable_defaults_and_variant(self):
        original = copy.deepcopy(self.document)
        planned = adaptor._native_plan(self.document)
        self.assertEqual(planned, adaptor._native_plan(self.document))
        self.assertEqual(self.document, original)
        self.assertTrue(all(page['rotate'] in (0, 90) for page in planned['pages']))
        self.assertEqual(planned['pages'][0], {'source': 'cover', 'page': 1, 'rotate': 0})
        self.assertEqual(planned['losses'], adaptor.LOSSES)
        variant = json.loads((ROOT / 'examples/schemaxis/qpdf-assemble-variant.json').read_text())
        self.assertNotEqual(planned, adaptor._native_plan(variant))

    def test_closed_request_and_exact_faults(self):
        self.fault({**self.document, 'pageLabels': 'drop'}, 'UNKNOWN_ARGUMENT')
        self.fault({**self.document, 'version': 'schemaxis.qpdf/2'}, 'UNSUPPORTED_VERSION', '$.version')
        self.fault({**self.document, 'operation': 'merge'}, 'UNKNOWN_FILTER', '$.operation')
        for key in ('sources', 'pages'):
            with self.assertRaises(SchemaxisError):
                adaptor._native_plan({k: v for k, v in self.document.items() if k != key})
        cases = [
            (lambda d: d['sources'][0].update(name='Cover'), 'INVALID_PDF_SOURCE_NAME', '$.sources[0].name'),
            (lambda d: d['sources'][0].update(name='1st'), 'INVALID_PDF_SOURCE_NAME', '$.sources[0].name'),
            (lambda d: d['sources'][0].update(name='a' * 25), 'INVALID_ARGUMENT', None),
            (lambda d: d['sources'][1].update(name='cover'), 'INVALID_PDF_SOURCE_NAME', '$.sources'),
            (lambda d: d['sources'][0].update(path='relative.pdf'), 'INVALID_PDF_SOURCE', '$.sources[0].path'),
            (lambda d: d['sources'][0].update(path='https://example.invalid/a.pdf'), 'INVALID_PDF_SOURCE', '$.sources[0].path'),
            (lambda d: d['sources'][0].update(path='/tmp/a.txt'), 'INVALID_PDF_SOURCE', '$.sources[0].path'),
            (lambda d: d['sources'][0].update(path='/tmp/a\x00.pdf'), 'INVALID_PDF_SOURCE', '$.sources[0].path'),
            (lambda d: d['sources'][1].update(path=d['sources'][0]['path']), 'INVALID_PDF_SOURCE', '$.sources'),
            (lambda d: d['pages'][1].update(source='appendix'), 'INVALID_PDF_PAGES', '$.pages[1].source'),
            (lambda d: d['pages'].__setitem__(slice(None), [p for p in d['pages'] if p['source'] == 'cover']), 'INVALID_PDF_SOURCES', '$.sources'),
            (lambda d: d['pages'][0].update(rotate=45), 'INVALID_ARGUMENT', '$.pages[0].rotate'),
            (lambda d: d['pages'][0].update(rotate=-90), 'INVALID_ARGUMENT', '$.pages[0].rotate'),
            (lambda d: d['pages'][0].update(page=0), 'INVALID_ARGUMENT', '$.pages[0].page'),
            (lambda d: d['pages'][0].update(page=501), 'INVALID_ARGUMENT', '$.pages[0].page'),
            (lambda d: d['pages'][0].update(page=True), 'INVALID_ARGUMENT', '$.pages[0].page'),
            (lambda d: d['pages'][0].update(extra=1), 'UNKNOWN_ARGUMENT', None),
            (lambda d: d.update(pages=d['pages'] * 41), 'INVALID_ARGUMENT', None),
            (lambda d: d.update(sources=d['sources'] + [{'name': c, 'path': '/tmp/%s.pdf' % c} for c in 'xyz']), 'INVALID_ARGUMENT', None)]
        for change, code, location in cases:
            with self.subTest(code=code, location=location):
                self.fault(self.mutated(change), code, location)

    def test_invalid_run_timeout_is_a_structured_fault_before_any_effect(self):
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / 'run'
            for bad in (0, -1, float('nan'), float('inf'), True, '5', None, 3601):
                with self.subTest(timeout=bad):
                    self.assertEqual(code_of(lambda: adaptor._native_run(self.document, target, executable='/x', oracle='/y', timeout=bad)), 'INVALID_ARGUMENT')
                    self.assertFalse(target.exists())

    def test_schema_matches_declarations(self):
        schema = adaptor.schema()
        self.assertEqual(set(schema['properties']), {'version', 'operation', 'sources', 'pages'})
        self.assertEqual(set(schema['required']), {'version', 'operation', 'sources', 'pages'})
        self.assertFalse(schema['additionalProperties'])
        pages = schema['properties']['pages']
        self.assertEqual((pages['minItems'], pages['maxItems']), (1, 200))
        self.assertEqual(set(pages['items']['properties']), {'source', 'page', 'rotate'})
        self.assertEqual(pages['items']['properties']['rotate']['enum'], [0, 90, 180, 270])
        self.assertEqual((schema['properties']['sources']['minItems'], schema['properties']['sources']['maxItems']), (1, 4))
        self.assertNotIn('pageLabels', json.dumps(schema))

    def test_registered_route_reuse_resources_and_query(self):
        from schemaxis.adaptors import registry
        self.assertEqual(registry.resolve({'version': adaptor.VERSION})[0], 'qpdf')
        self.assertEqual(adaptor.query(self.document), (['assemble'], {}))
        self.assertEqual(adaptor.resources(self.document, {}, 'x'), {'threads': 1})
        self.assertEqual(code_of(lambda: adaptor.resources(self.document, {'threads': 2}, 'x')), 'INVALID_EXECUTION')

    def test_reuse_identity_is_captured_byte_digests(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            files = {}
            for name in ('cover', 'report'):
                files[name] = directory / (name + '.pdf')
                files[name].write_bytes(b'%PDF-1.7\n' + name.encode())
            document = {**self.document, 'sources': [{'name': n, 'path': str(p)} for n, p in files.items()]}
            before = adaptor.reusableInputs(document)
            self.assertEqual(before['cover'], hashlib.sha256(files['cover'].read_bytes()).hexdigest())
            files['report'].write_bytes(b'%PDF-1.7\nchanged at the same path')
            after = adaptor.reusableInputs(document)
            self.assertEqual(before['cover'], after['cover'])
            self.assertNotEqual(before['report'], after['report'])
            files['report'].unlink()
            self.assertEqual(code_of(lambda: adaptor.reusableInputs(document)), 'INVALID_PDF_SOURCE')

    def test_bounded_reads_refuse_links_directories_and_oversize(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            pdf = directory / 'a.pdf'
            pdf.write_bytes(b'%PDF-x')
            link = directory / 'link.pdf'
            link.symlink_to(pdf)
            self.assertEqual(adaptor.bounded(pdf), b'%PDF-x')
            for target, limit in ((link, 100), (directory, 100), (pdf, 3), (directory / 'missing.pdf', 100)):
                with self.subTest(target=target.name):
                    self.assertEqual(code_of(lambda: adaptor.bounded(target, limit=limit)), 'VERIFICATION_FAILED')
            self.assertEqual(code_of(lambda: adaptor.bounded(link, 'INVALID_PDF_SOURCE', 100)), 'INVALID_PDF_SOURCE')


class QpdfAdmission(unittest.TestCase):
    def refused(self, code, pages, selected=(1,), **kwargs):
        self.assertEqual(code_of(lambda: admit(pages, selected, **kwargs)), code)

    def test_inheritance_defaults_and_local_overrides(self):
        geometry = admit([{}])['geometry'][1]
        self.assertEqual((geometry['mediaBox'], geometry['effective'], geometry['rotate'], geometry['userUnit']), (MEDIA, MEDIA, 0, 1))
        geometry = admit([{}], root={'/MediaBox': MEDIA}, mid={'/CropBox': [20, 30, 180, 270], '/Rotate': 90})['geometry'][1]
        self.assertEqual((geometry['effective'], geometry['rotate']), ([20, 30, 180, 270], 90))
        self.assertEqual(geometry['optionalBoxes']['TrimBox'], [20, 30, 180, 270])     # defaults to the effective crop
        geometry = admit([{'/Rotate': 0}], mid={'/Rotate': 90})['geometry'][1]
        self.assertEqual(geometry['rotate'], 0)                                         # local overrides inherited
        for rotate, expected in ((-90, 270), (450, 90), (360, 0)):
            self.assertEqual(admit([{'/Rotate': rotate}])['geometry'][1]['rotate'], expected)
        geometry = admit([{'/UserUnit': 2, '/MediaBox': [-100, -150, 100, 150]}])['geometry'][1]
        self.assertEqual((geometry['userUnit'], geometry['physical']), (2, [400, 600]))
        geometry = admit([{'/MediaBox': [10.25, 20.75, 210.5, 320.125]}])['geometry'][1]
        self.assertEqual(geometry['physical'], [200.25, 299.375])

    def test_null_absent_and_indirect_values(self):
        objects = {'obj:90 0 R': {'value': [0, 0, 120, 180]}, 'obj:91 0 R': {'value': 200}, 'obj:92 0 R': {'value': 2}}
        self.assertEqual(admit([{'/MediaBox': '90 0 R'}], objects=objects)['geometry'][1]['mediaBox'], [0, 0, 120, 180])
        self.assertEqual(admit([{'/MediaBox': [0, 0, '91 0 R', 300]}], objects=objects)['geometry'][1]['mediaBox'], [0, 0, 200, 300])
        self.assertEqual(admit([{'/UserUnit': '92 0 R'}], objects=objects)['geometry'][1]['userUnit'], 2)
        self.assertEqual(admit([{'/UserUnit': None}])['geometry'][1]['userUnit'], 1)           # null is absent
        self.assertEqual(admit([{'/MediaBox': None}])['geometry'][1]['mediaBox'], MEDIA)       # null inherits

    def test_geometry_refusals(self):
        bad = 'PDF_GEOMETRY_UNSUPPORTED'
        for label, body, root in [
            ('zero UserUnit', {'/UserUnit': 0}, '/MediaBox'), ('negative UserUnit', {'/UserUnit': -2}, '/MediaBox'),
            ('string UserUnit', {'/UserUnit': 'u:2'}, '/MediaBox'), ('boolean UserUnit', {'/UserUnit': True}, '/MediaBox'),
            ('huge UserUnit', {'/UserUnit': 75001}, '/MediaBox'),
            ('Rotate 45', {'/Rotate': 45}, '/MediaBox'), ('real Rotate', {'/Rotate': 90.0}, '/MediaBox'), ('string Rotate', {'/Rotate': 'u:90'}, '/MediaBox'),
            ('boolean Rotate', {'/Rotate': True}, '/MediaBox'),
            ('reversed MediaBox', {}, {'/MediaBox': [200, 300, 0, 0]}), ('empty MediaBox', {}, {'/MediaBox': [0, 0, 0, 0]}),
            ('three numbers', {}, {'/MediaBox': [0, 0, 200]}), ('name MediaBox', {}, {'/MediaBox': '/Letter'}),
            ('string numbers', {}, {'/MediaBox': ['u:0', 'u:0', 'u:200', 'u:300']}), ('boolean number', {}, {'/MediaBox': [0, 0, True, 300]}),
            ('huge coordinate', {}, {'/MediaBox': [0, 0, 1e9, 300]}), ('missing MediaBox', {}, None),
            ('CropBox outside', {'/CropBox': [-5, 0, 200, 300]}, '/MediaBox'), ('CropBox disjoint', {'/CropBox': [500, 500, 600, 600]}, '/MediaBox'),
            ('CropBox reversed', {'/CropBox': [180, 270, 20, 30]}, '/MediaBox'),
            ('TrimBox outside', {'/TrimBox': [-1, 0, 100, 100]}, '/MediaBox'), ('ArtBox reversed', {'/ArtBox': [100, 100, 0, 0]}, '/MediaBox'),
            ('dangling reference', {'/MediaBox': '999 0 R'}, None)]:
            with self.subTest(label):
                self.refused(bad, [body], root=root)

    def test_physical_size_and_pixel_budgets_count_userunit_and_repeats(self):
        self.refused('PDF_GEOMETRY_LIMIT', [{'/UserUnit': 75000, '/MediaBox': [0, 0, 8000, 8000]}])
        self.refused('PDF_GEOMETRY_LIMIT', [{'/MediaBox': [0, 0, 9000, 100]}])
        a4 = admit([{'/MediaBox': [0, 0, 595.276, 841.89]}])['geometry'][1]
        self.assertEqual(inspection.predicted_pixels(a4, 0), (298, 421))
        self.assertEqual(inspection.predicted_pixels(a4, 90), (421, 298))
        page = admit([{'/Rotate': 90, '/MediaBox': [0, 0, 595.276, 841.89]}])['geometry'][1]
        self.assertEqual(inspection.predicted_pixels(page, 0), (421, 298))
        self.assertEqual(inspection.predicted_pixels(page, 90), (298, 421))
        self.assertEqual(inspection.pixel_budget([(298, 421)] * 133), 133 * 298 * 421)
        self.assertEqual(code_of(lambda: inspection.pixel_budget([(298, 421)] * 134)), 'PDF_PIXEL_LIMIT')
        self.assertEqual(code_of(lambda: inspection.pixel_budget([(4097, 10)])), 'PDF_PIXEL_LIMIT')
        self.assertEqual(code_of(lambda: inspection.pixel_budget([(0, 10)])), 'PDF_PIXEL_LIMIT')
        self.assertEqual(inspection.pixel_budget([(4096, 4096)]), 4096 * 4096)

    def test_page_and_ancestor_allow_lists(self):
        allowed = {'/BleedBox': [1, 1, 199, 299], '/TrimBox': [2, 2, 198, 298], '/ArtBox': [3, 3, 197, 297], '/Annots': [], '/Resources': {}}
        self.assertEqual(admit([allowed])['pages'], 1)
        self.assertEqual(admit([{'/Annots': None}])['pages'], 1)
        for key in ('/StructParents', '/B', '/PresSteps', '/VP', '/SeparationInfo', '/Trans', '/Dur', '/AF', '/Metadata', '/AA', '/Foo', '/LastModified', '/Group'):
            with self.subTest(key):
                self.refused('PDF_PAGE_FEATURE_UNSUPPORTED', [{key: 1}])
        for annots in (['5 0 R'], [{'/Subtype': '/Link'}], 'u:x', 7):
            with self.subTest(annots=annots):
                self.refused('PDF_ANNOTATIONS_UNSUPPORTED', [{'/Annots': annots}])
        # Pages-node-only UserUnit and optional boxes never inherit and are refused.
        for key, value in (('/UserUnit', 2), ('/TrimBox', [1, 1, 100, 100]), ('/Foo', 1)):
            with self.subTest(ancestor=key):
                self.refused('PDF_PAGE_FEATURE_UNSUPPORTED', [{}], root={'/MediaBox': MEDIA, key: value})
                self.refused('PDF_PAGE_FEATURE_UNSUPPORTED', [{}], mid={key: value})

    def test_sibling_pages_are_only_read_when_selected(self):
        pages = [{}, {'/AA': {'/O': {'/S': '/JavaScript'}}}]
        self.assertEqual(admit(pages, (1,))['pages'], 2)
        self.refused('PDF_PAGE_FEATURE_UNSUPPORTED', pages, selected=(2,))
        self.refused('PDF_PAGE_RANGE', pages, selected=(3,))

    def test_catalogue_policy(self):
        for key in ('/Metadata', '/Outlines', '/Names', '/Dests', '/OpenAction', '/AA', '/PageLayout', '/PageMode', '/ViewerPreferences', '/Lang', '/PageLabels', '/Version'):
            with self.subTest(discarded=key):
                self.assertIn(key, admit([{}], catalogue={key: 1})['discarded'] + ['/Version'])
        for key in ('/AcroForm', '/Perms', '/OCProperties', '/OutputIntents', '/StructTreeRoot', '/MarkInfo', '/Threads', '/AF', '/Extensions', '/Foo'):
            with self.subTest(refused=key):
                self.refused('PDF_CATALOGUE_UNSUPPORTED', [{}], catalogue={key: 1})
        self.refused('ENCRYPTED_PDF', [{}], encrypted=True)
        self.refused('ENCRYPTED_PDF', [{}], trailer={'/Encrypt': '5 0 R'})

    def test_resource_scan_distinguishes_names_values_and_map_keys(self):
        def resources(**kind):
            return [{'/Resources': kind}]
        decoys = {'/Font': {'/JS': '5 0 R', '/Launch': '5 0 R', '/AA': '5 0 R', '/OC': '5 0 R', '/EF': '5 0 R'}}
        objects = {'obj:5 0 R': {'value': {'/Type': '/Font', '/Subtype': '/Type1', '/BaseFont': '/Launch'}},
                   'obj:96 0 R': {'value': {'/Type': '/Font', '/Subtype': '/Type3', '/CharProcs': {'/JS': '97 0 R'}, '/Encoding': {'/Differences': [65, '/JS']}}}}
        self.assertEqual(admit(resources(**decoys), objects=objects)['pages'], 1)
        self.assertEqual(admit(resources(**{'/Font': {'/T3': '96 0 R'}}), objects=objects)['pages'], 1)
        refusals = [
            ({'/Properties': {'x': {'/Type': '/OCG'}}}, 'OCG'), ({'/Properties': {'x': {'/Type': '/OCMD'}}}, 'OCMD'),
            ({'/Properties': {'x': {'/Type': '/Filespec', '/F': 'u:a'}}}, 'Filespec'), ({'/Properties': {'x': {'/Subtype': '/RichMedia'}}}, 'RichMedia'),
            ({'/Properties': {'x': {'/S': '/Launch'}}}, 'Launch'), ({'/ExtGState': {'g': {'/S': '/URI'}}}, 'URI'),
            ({'/ExtGState': {'g': {'/S': '/GoToR'}}}, 'GoToR'), ({'/Font': {'/F1': {'/JS': 'u:1'}}}, '/JS key'),
            ({'/XObject': {'/Fm': {'/OC': '1 0 R'}}}, '/OC key'), ({'/XObject': {'/Fm': {'/AA': {}}}}, '/AA key')]
        for entry, label in refusals:
            with self.subTest(label):
                self.refused('PDF_FEATURE_UNSUPPORTED', resources(**entry))
        self.refused('PDF_RESOURCE_UNSUPPORTED', resources(**{'/Foo': 1}))
        self.refused('PDF_RESOURCE_UNSUPPORTED', [{'/Resources': 7}])
        stream = {'obj:93 0 R': {'stream': {'dict': {'/Subtype': '/Image', '/F': 'u:external.bin', '/FFilter': '/Flate'}}}}
        self.refused('PDF_FEATURE_UNSUPPORTED', resources(**{'/XObject': {'/Im': '93 0 R'}}), objects=stream)
        contents = {'obj:100 0 R': {'stream': {'dict': {'/F': 'u:external.bin'}}}}
        self.refused('PDF_FEATURE_UNSUPPORTED', [{}], objects=contents)

    def test_external_reference_stream_entries_are_refused_but_resource_names_are_not(self):
        form = {'/Type': '/XObject', '/Subtype': '/Form', '/BBox': [0, 0, 10, 10]}
        for label, extra in (('reference XObject', {'/Ref': {'/F': 'u:other.pdf', '/Page': 1}}),
                             ('OPI', {'/OPI': {'/2.0': {'/Type': '/OPI', '/Version': 2.0, '/F': 'u:external.eps'}}}),
                             ('external file', {'/F': 'u:external.bin'})):
            with self.subTest(label):
                objects = {'obj:93 0 R': {'stream': {'dict': {**form, **extra}}}}
                self.refused('PDF_FEATURE_UNSUPPORTED', [{'/Resources': {'/XObject': {'/Fm1': '93 0 R'}}}], objects=objects)
        decoys = {'/XObject': {'/Ref': '93 0 R', '/OPI': '93 0 R'}}
        self.assertEqual(admit([{'/Resources': decoys}], objects={'obj:93 0 R': {'stream': {'dict': form}}})['pages'], 1)

    def test_direct_parent_message_names_the_cause(self):
        with self.assertRaises(SchemaxisError) as raised:
            admit([{'/Parent': {'/Type': '/Pages', '/MediaBox': MEDIA}}])
        fault = raised.exception.fault
        self.assertEqual(fault.code, 'PDF_GEOMETRY_UNSUPPORTED')
        self.assertIn('direct object', fault.message)
        with self.assertRaises(SchemaxisError) as plain:
            admit([{}], root={})
        self.assertNotIn('direct object', plain.exception.fault.message)             # a genuinely missing MediaBox keeps the plain message

    def test_inherited_resources_are_scanned_and_local_resources_replace_them(self):
        bad = {'/MediaBox': MEDIA, '/Resources': {'/Properties': {'x': {'/Type': '/OCG'}}}}
        self.refused('PDF_FEATURE_UNSUPPORTED', [{}], root=bad)
        self.assertEqual(admit([{'/Resources': {'/Font': {}}}], root=bad)['pages'], 1)

    def test_graph_bounds_cycles_and_depth(self):
        objects = {'obj:%d 0 R' % i: {'value': {'/Next': '%d 0 R' % (i + 1)}} for i in range(200, 260)}
        deep = [{'/Resources': {'/Properties': {'x': '200 0 R'}}}]
        self.refused('PDF_STRUCTURE_LIMIT', deep, objects=objects)
        shallow = {'obj:%d 0 R' % i: {'value': {'/Next': '%d 0 R' % (i + 1)}} for i in range(200, 222)}
        self.assertEqual(admit(deep, objects=shallow)['pages'], 1)
        cycle = {'obj:300 0 R': {'value': {'/Next': '301 0 R'}}, 'obj:301 0 R': {'value': {'/Next': '300 0 R'}}}
        self.assertEqual(admit([{'/Resources': {'/Properties': {'x': '300 0 R'}}}], objects=cycle)['pages'], 1)
        loop = {'obj:3 0 R': {'value': {'/Type': '/Pages', '/Parent': '4 0 R'}}, 'obj:4 0 R': {'value': {'/Type': '/Pages', '/Parent': '3 0 R'}}}
        self.refused('PDF_PAGE_TREE', [{}], mid={}, objects={**loop, 'obj:10 0 R': {'value': {'/Type': '/Page', '/Parent': '3 0 R'}}})
        chain = {'obj:%d 0 R' % i: {'value': '%d 0 R' % (i + 1)} for i in range(400, 430)}
        self.refused('PDF_STRUCTURE_LIMIT', [{'/MediaBox': '400 0 R'}], objects=chain)
        nodes = {'obj:%d 0 R' % i: {'value': {'/Type': '/Pages', '/Parent': '%d 0 R' % (i + 1)}} for i in range(500, 540)}
        nodes['obj:10 0 R'] = {'value': {'/Type': '/Page', '/Parent': '500 0 R'}}
        self.refused('PDF_PAGE_TREE', [{}], objects=nodes)
        with patch.object(inspection, 'MAX_OBJECTS', 5):
            self.refused('PDF_STRUCTURE_LIMIT', [{'/Resources': {'/Properties': {str(i): '%d 0 R' % (200 + i) for i in range(20)}}}], objects=objects)

    def test_page_limits(self):
        self.refused('PDF_PAGE_RANGE', [{}], selected=(2,))
        with patch.object(inspection, 'MAX_SOURCE_PAGES', 1):
            self.refused('PDF_PAGE_LIMIT', [{}, {}])


class QpdfCapturePolicy(unittest.TestCase):
    """One capture policy for run and saved verification: standard header, 16 MiB each (bounded read), 32 MiB together."""
    MIB = 1024 * 1024

    def document(self, directory, count=3):
        names = ['one', 'two', 'three'][:count]
        return {'version': adaptor.VERSION, 'operation': 'assemble',
                'sources': [{'name': n, 'path': str(Path(directory) / (n + '.pdf'))} for n in names], 'pages': [{'source': n, 'page': 1} for n in names]}

    def blob(self, size, header=b'%PDF-1.7\n'):
        return header + bytes(size - len(header))

    def no_native(self):
        def refuse(*args, **kwargs):
            raise AssertionError('a native launch happened before the capture policy refused')
        return patch.object(adaptor, 'launch', refuse)

    def test_policy_function_boundaries_and_codes(self):
        self.assertEqual(adaptor.capture_policy(b'%PDF-x', 0, 'C', 'here'), 6)
        self.assertEqual(adaptor.capture_policy(self.blob(16 * self.MIB), 16 * self.MIB, 'C', 'here'), 32 * self.MIB)     # exactly 32 MiB is accepted
        for data, total in ((self.blob(self.MIB), 31 * self.MIB + 1), (b'%PDF', 0), (b'', 0), (b'xPDF-1', 0)):
            with self.subTest(size=len(data), total=total):
                self.assertEqual(code_of(lambda: adaptor.capture_policy(data, total, 'FAULT', 'here')), 'FAULT')

    def test_run_and_saved_verification_refuse_the_same_aggregate_bytes(self):
        with tempfile.TemporaryDirectory() as raw, self.no_native():
            directory = Path(raw)
            document = self.document(directory)
            blobs = [self.blob(11 * self.MIB + 700000)] * 3                 # each under 16 MiB, 34.6 MB together (the supervisor's probe size)
            self.assertGreater(sum(map(len, blobs)), adaptor.MAX_TOTAL_SOURCE_BYTES)
            for entry, data in zip(document['sources'], blobs):
                Path(entry['path']).write_bytes(data)
            with self.assertRaises(SchemaxisError) as ran:
                adaptor._native_run(document, directory / 'run', executable='/bin/true', oracle='/bin/true', timeout=30)
            self.assertEqual((ran.exception.fault.code, ran.exception.fault.location), ('INVALID_PDF_SOURCE', '$.sources[2].path'))
            self.assertFalse((directory / 'run' / 'assembled.pdf').exists())
            saved = directory / 'saved'
            saved.mkdir()
            atomic = lambda name, value: (saved / name).write_text(json.dumps(value))
            atomic('authored.json', document)
            atomic('plan.json', adaptor._native_plan(document))
            atomic('result.json', {'status': 'succeeded', 'verified': True})
            for entry, data in zip(document['sources'], blobs):
                (saved / ('source-%s.pdf' % entry['name'])).write_bytes(data)
            with self.assertRaises(SchemaxisError) as verified:
                adaptor.verify_semantic(saved, {'qpdf': '/bin/true', 'mupdf': '/bin/true'})
            self.assertEqual(verified.exception.fault.code, 'VERIFICATION_FAILED')
            self.assertIn('retained captured source three', verified.exception.fault.location)

    def test_saved_verification_applies_the_header_policy_and_the_per_source_bound(self):
        with tempfile.TemporaryDirectory() as raw, self.no_native():
            directory = Path(raw)
            document = self.document(directory, 2)
            saved = directory / 'saved'
            saved.mkdir()
            (saved / 'authored.json').write_text(json.dumps(document))
            (saved / 'plan.json').write_text(json.dumps(adaptor._native_plan(document)))
            (saved / 'result.json').write_text(json.dumps({'status': 'succeeded'}))
            paths = {'qpdf': '/bin/true', 'mupdf': '/bin/true'}
            (saved / 'source-one.pdf').write_bytes(self.blob(1000))
            (saved / 'source-two.pdf').write_bytes(b'NOT A PDF\n' + bytes(100))
            with self.assertRaises(SchemaxisError) as header:
                adaptor.verify_semantic(saved, paths)
            self.assertEqual((header.exception.fault.code, header.exception.fault.location), ('VERIFICATION_FAILED', 'retained captured source two'))
            (saved / 'source-two.pdf').write_bytes(self.blob(16 * self.MIB + 1))
            self.assertEqual(code_of(lambda: adaptor.verify_semantic(saved, paths)), 'VERIFICATION_FAILED')       # over the per-source bound

    def test_sources_within_the_policy_proceed_to_native_work(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            document = self.document(directory, 2)
            for entry in document['sources']:
                Path(entry['path']).write_bytes(self.blob(16 * self.MIB))            # 32 MiB together: exactly at the aggregate limit
            reached = []
            def stop(*args, **kwargs):
                reached.append(args[1])
                raise SchemaxisError(__import__('schemaxis.core.faults', fromlist=['Fault']).Fault('RUNNER_CANCELLED', 'stop here', 'x', 'pipeline'))
            with patch.object(adaptor, 'launch', stop):
                self.assertEqual(code_of(lambda: adaptor._native_run(document, directory / 'run', executable='/bin/true', oracle='/bin/true', timeout=30)), 'RUNNER_CANCELLED')
            self.assertEqual(reached, ['version-qpdf'])                              # the policy accepted the sources; the first native stage was reached


class QpdfJson(unittest.TestCase):
    def fault(self, data, code):
        self.assertEqual(code_of(lambda: inspection.parse(data, 'x')), code)

    def test_native_json_is_bounded_and_shape_checked(self):
        good = synthetic([{}])
        self.assertEqual(inspection.parse(good, 'x')['version'], 2)
        self.fault(b'not json', 'PDF_STRUCTURE_UNSUPPORTED')
        self.fault(b'[]', 'PDF_STRUCTURE_UNSUPPORTED')
        self.fault(b'{"version": 2}', 'PDF_STRUCTURE_UNSUPPORTED')
        self.fault(json.dumps({'version': 1, 'pages': [], 'encrypt': {}, 'qpdf': [{}, {'trailer': {'value': {}}}]}).encode(), 'PDF_STRUCTURE_UNSUPPORTED')
        self.fault(json.dumps({'version': 2, 'pages': {}, 'encrypt': {}, 'qpdf': [{}, {'trailer': {'value': {}}}]}).encode(), 'PDF_STRUCTURE_UNSUPPORTED')
        self.fault(b'\xff\xfe', 'PDF_STRUCTURE_UNSUPPORTED')
        self.fault(b'[' * 20000, 'PDF_STRUCTURE_LIMIT')
        with patch.object(inspection, 'MAX_JSON_BYTES', 10):
            self.fault(good, 'PDF_STRUCTURE_LIMIT')
        with patch.object(inspection, 'MAX_OBJECTS', 3):
            self.fault(good, 'PDF_STRUCTURE_LIMIT')
        text = good.decode().replace('"version": 2', '"text": "' + '\u00e9' * 12 + '", "version": 2')
        with patch.object(inspection, 'MAX_JSON_BYTES', len(text) + 1):
            self.fault(text, 'PDF_STRUCTURE_LIMIT')

    def test_json_nesting_bound_is_explicit_and_preserves_quoted_content(self):
        good = json.loads(synthetic([{}]))
        # The root object is one container; exactly 127 nested arrays fit.
        for containers, accepted in ((127, True), (128, False)):
            document = (json.dumps(good)[:-1] + ', "nested": ' + '[' * containers
                        + '0' + ']' * containers + '}').encode()
            with self.subTest(containers=containers):
                if accepted:
                    self.assertEqual(inspection.parse(document, 'x')['version'], 2)
                else:
                    self.fault(document, 'PDF_STRUCTURE_LIMIT')
        self.fault(b'{"a":' * 129, 'PDF_STRUCTURE_LIMIT')
        self.fault(b'[' * 20000 + b'0' + b']' * 20000, 'PDF_STRUCTURE_LIMIT')
        good['text'] = '[{\\"' * 20000 + '\u00e9' + '\\\\' + '}]' * 20000
        self.assertEqual(inspection.parse(json.dumps(good, ensure_ascii=False).encode(), 'x')['text'], good['text'])
        self.fault(b'{"text":"' + b'[' * 20000, 'PDF_STRUCTURE_UNSUPPORTED')
        self.fault(b'}' + b'[' * 20000, 'PDF_STRUCTURE_UNSUPPORTED')
        self.assertEqual(code_of(lambda: inspection.parse(b'[' * 129, 'x', 'VERIFICATION_FAILED')), 'PDF_STRUCTURE_LIMIT')

    def test_malformed_structure_is_a_declared_fault_not_a_python_exception(self):
        for catalogue in ('/Metadata',):
            data = json.loads(synthetic([{}]))
            data['qpdf'][1]['obj:1 0 R'] = {'value': 5}
            doc = inspection.Document(inspection.parse(json.dumps(data).encode(), 'x'), 'x')
            self.assertEqual(code_of(lambda: inspection.admit_source(doc, (1,))), 'PDF_STRUCTURE_UNSUPPORTED')
        data = json.loads(synthetic([{}]))
        data['pages'] = [{'object': 7}]
        doc = inspection.Document(inspection.parse(json.dumps(data).encode(), 'x'), 'x')
        self.assertEqual(code_of(lambda: inspection.admit_source(doc, (1,))), 'PDF_STRUCTURE_UNSUPPORTED')
        data = json.loads(synthetic([{}]))
        data['qpdf'][1]['obj:2 0 R'] = {'value': {'/Kids': 'oops', '/MediaBox': {'a': 1}}}
        doc = inspection.Document(inspection.parse(json.dumps(data).encode(), 'x'), 'x')
        self.assertEqual(code_of(lambda: inspection.admit_source(doc, (1,))), 'PDF_GEOMETRY_UNSUPPORTED')


def finals(positions, pages, sources_pages, **kwargs):
    """Admit synthetic sources and check a synthetic published document against positions."""
    admitted = {name: inspection.admit_source(document(body, label=name), selected) for name, (body, selected) in sources_pages.items()}
    return inspection.check_final(document(pages, label='final', root=kwargs.pop('root', {}), **kwargs), positions, admitted)


class QpdfFinalEnvelope(unittest.TestCase):
    SOURCES = {'a': ([{}, {'/Rotate': 90, '/MediaBox': [0, 0, 100, 150]}], (1, 2))}

    def final(self, positions, pages, **kwargs):
        return finals(positions, pages, self.SOURCES, **kwargs)

    def fault(self, positions, pages, **kwargs):
        self.assertEqual(code_of(lambda: self.final(positions, pages, **kwargs)), 'VERIFICATION_FAILED')

    def test_matching_publication_passes_with_repeats_and_relative_rotation(self):
        positions = [('a', 2, 0), ('a', 1, 90), ('a', 1, 0), ('a', 2, 270)]
        pages = [{'/MediaBox': [0, 0, 100, 150], '/Rotate': 90}, {'/MediaBox': MEDIA, '/Rotate': 90}, {'/MediaBox': MEDIA},
                 {'/MediaBox': [0, 0, 100, 150], '/Rotate': 0}]
        self.assertEqual(len(self.final(positions, pages)), 4)

    def test_order_count_rotation_boxes_and_userunit_are_checked(self):
        positions = [('a', 1, 0), ('a', 2, 0)]
        good = [{'/MediaBox': MEDIA}, {'/MediaBox': [0, 0, 100, 150], '/Rotate': 90}]
        self.assertEqual(len(self.final(positions, good)), 2)
        self.fault(positions, good[::-1])
        self.fault(positions, good[:1])
        self.fault(positions, good + [{'/MediaBox': MEDIA}])
        self.fault(positions, [good[0], {'/MediaBox': [0, 0, 100, 150], '/Rotate': 180}])
        self.fault(positions, [good[0], {'/MediaBox': [0, 0, 100, 150]}])
        self.fault(positions, [{'/MediaBox': [0, 0, 200, 299]}, good[1]])
        self.fault(positions, [{'/MediaBox': MEDIA, '/CropBox': [0, 0, 100, 100]}, good[1]])
        self.fault(positions, [{'/MediaBox': MEDIA, '/UserUnit': 2}, good[1]])
        self.fault(positions, [{'/MediaBox': MEDIA, '/TrimBox': [1, 1, 100, 100]}, good[1]])

    def test_published_page_must_use_allow_listed_keys_and_no_annotations(self):
        positions = [('a', 1, 0)]
        for extra in ({'/AA': {}}, {'/Annots': ['5 0 R']}, {'/StructParents': 0}, {'/Resources': {'/Properties': {'x': {'/Type': '/OCG'}}}}):
            with self.subTest(extra=extra):
                self.fault(positions, [{'/MediaBox': MEDIA, **extra}])

    def test_catalogue_trailer_and_encryption_of_the_publication(self):
        positions = [('a', 1, 0)]
        page = [{'/MediaBox': MEDIA}]
        for catalogue in ({'/OpenAction': 1}, {'/Metadata': '5 0 R'}, {'/PageLabels': {}}, {'/Outlines': 1}):
            with self.subTest(catalogue=catalogue):
                self.fault(positions, page, catalogue=catalogue)
        self.fault(positions, page, trailer={'/Info': '9 0 R'})
        self.fault(positions, page, trailer={'/Encrypt': '9 0 R'})
        self.fault(positions, page, encrypted=True)
        xref = {'/Type': '/XRef', '/W': [1, 2, 1], '/Filter': '/FlateDecode', '/DecodeParms': {}, '/Length': 40, '/Index': [0, 3]}
        self.assertEqual(len(self.final(positions, page, trailer=xref)), 1)
        self.fault(positions, page, trailer={'/W': [1, 2, 1]})
        self.fault(positions, page, trailer={'/Type': '/XRef', '/Prev': 4})

    def test_repeated_page_objects_in_the_tree_are_refused(self):
        data = json.loads(synthetic([{'/MediaBox': MEDIA}, {'/MediaBox': MEDIA}], root={}))
        data['pages'] = [{'object': '10 0 R'}, {'object': '10 0 R'}]
        admitted = {'a': inspection.admit_source(document([{}], label='a'), (1,))}
        final = inspection.Document(inspection.parse(json.dumps(data).encode(), 'f'), 'f')
        self.assertEqual(code_of(lambda: inspection.check_final(final, [('a', 1, 0), ('a', 1, 0)], admitted)), 'VERIFICATION_FAILED')


class QpdfNativeMechanics(unittest.TestCase):
    def prepared(self):
        return adaptor._native_plan(json.loads((ROOT / 'examples/schemaxis/qpdf-assemble.json').read_text()))

    def test_assembly_command_contains_only_fixed_names_and_planned_integers(self):
        command = adaptor.assemble_command({'qpdf': '/trusted/qpdf'}, self.prepared())
        self.assertEqual(command[:4], ['/trusted/qpdf', '--suppress-recovery', '--empty', '--pages'])
        pages = command[4:command.index('--')]
        self.assertEqual(pages, ['source-cover.pdf', '1', 'source-report.pdf', '2', 'source-report.pdf', '1', 'source-report.pdf', '3', 'source-report.pdf', '3'])
        tail = command[command.index('--') + 1:]
        self.assertEqual(tail, ['--rotate=+90:5', '--remove-page-labels', '--deterministic-id', '--stream-data=preserve', '--object-streams=preserve', 'assembled.pdf'])
        self.assertNotIn('--warning-exit-0', command)
        self.assertFalse(any('/' in part for part in command[1:]))

    def test_launcher_has_caps_input_binding_and_no_authored_text(self):
        text = adaptor.launcher('check-cover', ['source-cover.pdf'], ['/trusted/qpdf', '--check', 'source-cover.pdf'], 1 << 30)
        for fragment in ('RLIMIT_AS,(1073741824', 'RLIMIT_FSIZE,(67108864', 'RLIMIT_CPU,(120', 'O_NOFOLLOW', 'check-cover-inputs.json', 'os.execvpe'):
            self.assertIn(fragment, text)
        compile(text, 'launcher', 'exec')

    def test_trusted_observer_script_is_passive_in_memory_and_path_free(self):
        jobs = [{'file': 'source-cover.pdf', 'page': 1, 'rotation': 90, 'output': 'e1.pnm'}, {'file': 'final.pdf', 'page': 1, 'rotation': None, 'output': 'a1.pnm'}]
        script = observer_source(jobs, 36, 4096, 16777216, 1048576, 4194304)
        self.assertTrue(script.startswith('var config = '))
        for fragment in ('doc.newInteger(j.rotation)', 'obj.put("Rotate"', 'getInheritable("Rotate")', 'wasRepaired()', 'getTrailer().get("Encrypt")', 'PDF_PIXEL_LIMIT',
                         'PDF_PIXEL_MISMATCH', 'saveAsPNM(j.output)', 'o.get(name)'):
            self.assertIn(fragment, script)
        for forbidden in ('enableJS', 'executeAction', 'getLinks', 'getAnnotations', 'save(', 'saveAsPDF', 'write(', 'loadPage(0)'):
            self.assertNotIn(forbidden, script)
        self.assertNotIn('getInheritable("UserUnit")', script)
        self.assertNotIn('getInheritable("MediaBox")', script)
        config = json.loads(script.split(';\n', 1)[0][len('var config = '):])
        self.assertEqual(config['jobs'], jobs)
        hostile = observer_source([{'file': 'x"); evil(); ("', 'page': 1, 'rotation': None, 'output': 'o.pnm'}], 36, 4096, 16777216, 1, 1)
        self.assertEqual(json.loads(hostile.split(';\n', 1)[0][len('var config = '):])['jobs'][0]['file'], 'x"); evil(); ("')

    def test_evidence_membership_and_publications(self):
        prepared = self.prepared()
        names = adaptor.evidence_names(prepared)
        self.assertIn('source-cover.pdf', names)
        self.assertIn('check-report-submission.json', names)
        self.assertIn('assemble-launcher.py', names)
        self.assertNotIn('assembled.pdf', names)
        self.assertNotIn('assembly-summary.json', names)
        listing = adaptor.publications('/run', b'pdf', b'summary')
        self.assertEqual([p['kind'] for p in listing], ['pdf', 'text'])
        self.assertEqual(listing[0]['sha256'], hashlib.sha256(b'pdf').hexdigest())
        self.assertEqual(listing[0]['file'], '/run/assembled.pdf')


class Executables(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = self.root / 'config.json'
        self.config.write_text('{"version": 1, "locations": {}}')
        self.environment = patch.dict(os.environ, {'SCHEMAXIS_CONFIG': str(self.config)})
        self.environment.start()
        for key in ('SCHEMAXIS_QPDF', 'SCHEMAXIS_MUPDF'):
            os.environ.pop(key, None)

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def tool(self, name, body='exit 0\n'):
        path = self.root / name
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o755)
        return str(path)

    def test_resolution_precedence_and_refusals(self):
        a, b, c, d = (self.tool(n) for n in 'abcd')
        self.assertEqual(code_of(adaptor.runtime), 'INTERPRETER_NOT_FOUND')
        os.environ.update(SCHEMAXIS_QPDF=a, SCHEMAXIS_MUPDF=b)
        self.assertEqual(adaptor.runtime(), {'qpdf': a, 'mupdf': b})                       # documented environment last
        with location_context({'qpdf': c, 'mupdf': d}):
            self.assertEqual(adaptor.runtime(), {'qpdf': c, 'mupdf': d})                   # context beats environment
            self.assertEqual(adaptor.runtime(qpdf=a), {'qpdf': a, 'mupdf': d})             # explicit beats context
        self.config.write_text(json.dumps({'version': 1, 'locations': {'qpdf': c, 'mupdf': d}}))
        self.assertEqual(adaptor.runtime(), {'qpdf': c, 'mupdf': d})                       # stored configuration beats environment
        for bad in ('relative/qpdf', str(self.root / 'missing'), str(self.root)):
            with self.subTest(bad=bad):
                self.assertEqual(code_of(lambda: adaptor.runtime(qpdf=bad)), 'INTERPRETER_NOT_FOUND')
        plain = self.root / 'plain'
        plain.write_text('x')
        self.assertEqual(code_of(lambda: adaptor.runtime(qpdf=str(plain))), 'INTERPRETER_NOT_FOUND')

    def test_receipt_executables_never_become_authority(self):
        canary = self.root / 'CANARY'
        evil = self.tool('evil', 'touch %s\n' % canary)
        run = self.root / 'run'
        run.mkdir()
        (run / 'verification.json').write_text(json.dumps({'executables': {'qpdf': evil, 'mupdf': evil}, 'runtime': 'x'}))
        self.assertEqual(code_of(lambda: adaptor.verify(run)), 'INTERPRETER_NOT_FOUND')
        self.assertFalse(canary.exists())

    def test_identity_is_pinned_and_a_wrong_release_faults(self):
        good = {'qpdf': self.tool('q', 'echo "qpdf version 12.4.2"\n'), 'mupdf': self.tool('m', 'echo "mutool version 1.28.5" >&2\n')}
        work = self.root / 'work'
        work.mkdir()
        self.assertEqual(adaptor.identity(good, work), 'qpdf version 12.4.2; mutool version 1.28.5')
        for key, body in (('qpdf', 'echo "qpdf version 9.9.9"\n'), ('mupdf', 'echo "mutool version 1.23.10"\n'), ('qpdf', 'exit 3\n'), ('mupdf', 'true\n')):
            with self.subTest(key=key, body=body):
                fake = dict(good, **{key: self.tool('x' + key, body)})
                self.assertEqual(code_of(lambda: adaptor.identity(fake, work)), 'UNSUPPORTED_RUNTIME')

    def test_every_native_launch_consults_cancellation_and_the_cumulative_deadline_first(self):
        import threading
        work = self.root / 'launch'
        work.mkdir()
        with patch.object(adaptor, 'execute') as execute:
            with execution_deadline(1e-6):
                import time
                time.sleep(0.01)
                self.assertEqual(code_of(lambda: adaptor.launch(work, 'x', ['/bin/true'])), 'RUNNER_TIMED_OUT')
            cancel = threading.Event()
            cancel.set()
            with allocation({'threads': 1, 'ranks': 1}, cancel):
                self.assertEqual(code_of(lambda: adaptor.launch(work, 'x', ['/bin/true'])), 'RUNNER_CANCELLED')
            execute.assert_not_called()

    def test_failed_exit_codes_and_output_limits_map_to_declared_faults(self):
        from schemaxis.core.faults import Fault
        work = self.root / 'exit'
        work.mkdir()
        def failing(code):
            def run(*args, **kwargs):
                (work / 'x.stdout').write_bytes(b'out')
                (work / 'x.stderr').write_bytes(b'err')
                raise SchemaxisError(Fault('RUNNER_FAILED', 'native execution did not complete', 'x', 'pipeline', observed={'exitCode': code}))
            return run
        with patch.object(adaptor, 'execute', failing(3)):
            self.assertEqual(adaptor.launch(work, 'x', ['/bin/true']), (3, b'out', b'err'))
        with patch.object(adaptor, 'execute', failing(-25)):
            self.assertEqual(code_of(lambda: adaptor.launch(work, 'x', ['/bin/true'])), 'PDF_STRUCTURE_LIMIT')
        def timed_out(*args, **kwargs):
            raise SchemaxisError(Fault('RUNNER_TIMED_OUT', 'late', 'x', 'pipeline'))
        with patch.object(adaptor, 'execute', timed_out):
            self.assertEqual(code_of(lambda: adaptor.launch(work, 'x', ['/bin/true'])), 'RUNNER_TIMED_OUT')

    def test_qpdf_failures_are_translated_before_publication(self):
        document = synthetic([{}])
        def launches(*results):
            queue = iter(results)
            return patch.object(adaptor, 'launch', lambda *a, **k: next(queue))
        work = self.root
        paths = {'qpdf': '/q'}
        with launches((0, b'ok', b''), (0, document, b'')):
            self.assertIsInstance(adaptor.inspect_pdf(paths, work, 'a.pdf', 'a', 'source a'), inspection.Document)
        cases = [((2, b'', b'qpdf: a.pdf: invalid password'), 'ENCRYPTED_PDF', 'INVALID_PDF_SOURCE'),
                 ((3, b'', b'WARNING: a.pdf: file is damaged'), 'PDF_REPAIRED', 'VERIFICATION_FAILED'),
                 ((0, b'', b'noise on stderr'), 'PDF_REPAIRED', 'VERIFICATION_FAILED'),
                 ((2, b'', b'qpdf: unreadable'), 'INVALID_PDF_SOURCE', 'VERIFICATION_FAILED')]
        for result, as_source, as_final in cases:
            for source, expected in ((True, as_source), (False, as_final if as_source != 'ENCRYPTED_PDF' else 'ENCRYPTED_PDF')):
                with self.subTest(result=result, source=source), launches(result):
                    self.assertEqual(code_of(lambda: adaptor.inspect_pdf(paths, work, 'a.pdf', 'a', 'x', source=source)), expected)
        with launches((0, b'ok', b''), (0, b'{"broken"', b'')):
            self.assertEqual(code_of(lambda: adaptor.inspect_pdf(paths, work, 'a.pdf', 'a', 'x')), 'PDF_STRUCTURE_UNSUPPORTED')
        with launches((0, b'ok', b''), (0, b'{"broken"', b'')):
            self.assertEqual(code_of(lambda: adaptor.inspect_pdf(paths, work, 'a.pdf', 'a', 'x', source=False)), 'VERIFICATION_FAILED')
        with launches((0, b'ok', b''), (1, b'', b'')):
            self.assertEqual(code_of(lambda: adaptor.inspect_pdf(paths, work, 'a.pdf', 'a', 'x')), 'INVALID_PDF_SOURCE')


def record(page, geometry, rotate, pixels, text='t', digest='d', count=1, original=None, bounds=None, unit=None):
    return {'page': page, 'pageCount': count, 'originalRotate': geometry['rotate'] if original is None else original,
            'bounds': bounds or [0, 0, 1, 1], 'userUnit': unit, 'mediaBox': geometry['mediaBox'], 'cropBox': None,
            'rotation': (geometry['rotate'] + rotate) % 360, 'predicted': list(pixels), 'pixmap': list(pixels), 'text': text, 'rasterSha256': digest}


class QpdfObservationComparison(unittest.TestCase):
    """Every branch of observe_all's exact comparison, driven by canned native observations."""

    def setUp(self):
        self.prepared = adaptor._native_plan({'version': adaptor.VERSION, 'operation': 'assemble',
            'sources': [{'name': 'a', 'path': '/tmp/a.pdf'}], 'pages': [{'source': 'a', 'page': 1}, {'source': 'a', 'page': 1, 'rotate': 90}]})
        self.admitted = {'a': inspection.admit_source(document([{}], label='a'), (1,))}
        self.geometry = self.admitted['a']['geometry'][1]
        self.final = document([{'/MediaBox': MEDIA}, {'/MediaBox': MEDIA, '/Rotate': 90}], root={}, label='final')

    def observations(self, **changes):
        sizes = [inspection.predicted_pixels(self.geometry, 0), inspection.predicted_pixels(self.geometry, 90)]
        expected = [record(1, self.geometry, 0, sizes[0]), record(1, self.geometry, 90, sizes[1])]
        actual = [record(1, self.geometry, 0, sizes[0], count=2), record(2, self.geometry, 90, sizes[1], count=2)]
        for key, value in changes.items():
            side, index, field = key.split('_')
            target = (expected if side == 'e' else actual)[int(index)]
            target[field] = value
        return expected, actual

    def run_all(self, **changes):
        expected, actual = self.observations(**changes)
        replies = iter([expected, actual])
        with patch.object(adaptor, 'inspect_pdf', lambda *a, **k: self.final), patch.object(adaptor, 'observe', lambda *a, **k: next(replies)):
            return adaptor.observe_all({'qpdf': '/q', 'mupdf': '/m'}, '/scratch', self.prepared, self.admitted)

    def test_consistent_observations_produce_the_regenerable_summary(self):
        summary = self.run_all()
        self.assertEqual(summary['pageCount'], 2)
        self.assertEqual([p['rotate'] for p in summary['pages']], [0, 90])
        self.assertEqual(summary, self.run_all())
        self.assertEqual(summary['sources'], [{'name': 'a', 'pages': 1, 'discarded': []}])
        self.assertEqual(json.loads(json.dumps(summary)), summary)

    def test_each_independent_difference_is_a_verification_failure(self):
        changes = {'raster': {'a_1_rasterSha256': 'x'}, 'text': {'a_0_text': 'other'}, 'bounds': {'a_0_bounds': [0, 0, 2, 2]}, 'pixmap': {'a_1_pixmap': [1, 1]},
                   'unit': {'a_0_userUnit': 2}, 'predicted': {'e_0_predicted': [9, 9]}, 'page count': {'a_0_pageCount': 3},
                   'qpdf/mupdf rotation disagreement': {'e_1_originalRotate': 90}, 'published rotation': {'a_1_rotation': 0}}
        for label, change in changes.items():
            with self.subTest(label):
                self.assertEqual(code_of(lambda: self.run_all(**change)), 'VERIFICATION_FAILED')

    def test_budget_is_enforced_before_any_observer_runs(self):
        launched = []
        with patch.object(adaptor, 'inspect_pdf', lambda *a, **k: launched.append('final')), patch.object(adaptor, 'observe', lambda *a, **k: launched.append('observe')):
            big = copy.deepcopy(self.prepared)
            big['pages'] = [{'source': 'a', 'page': 1, 'rotate': 0}] * 200
            wide = {'a': inspection.admit_source(document([{'/MediaBox': [0, 0, 8000, 8000]}], label='a'), (1,))}
            self.assertEqual(code_of(lambda: adaptor.observe_all({'qpdf': '/q', 'mupdf': '/m'}, '/s', big, wide)), 'PDF_PIXEL_LIMIT')
        self.assertEqual(launched, [])

    def test_observer_records_are_closed_and_typed(self):
        jobs = [('source-a.pdf', 1, None)]
        base = {'page': 1, 'pageCount': 1, 'originalRotate': 0, 'bounds': [0, 0, 1, 1], 'userUnit': None, 'mediaBox': None, 'cropBox': None,
                'rotation': 0, 'predicted': [1, 1], 'pixmap': [1, 1], 'text': ''}
        self.assertEqual(adaptor.observer_records(json.dumps([base]).encode(), jobs, 'x'), [base])
        for label, bad in {'extra key': {**base, 'x': 1}, 'bool page': {**base, 'page': True}, 'wrong page': {**base, 'page': 2}, 'nan bound': {**base, 'bounds': [0, 0, 1, float('nan')]},
                           'short bounds': {**base, 'bounds': [0, 0, 1]}, 'float size': {**base, 'pixmap': [1.5, 1]}, 'text type': {**base, 'text': 5},
                           'count range': {**base, 'pageCount': 0}}.items():
            with self.subTest(label):
                self.assertEqual(code_of(lambda: adaptor.observer_records(json.dumps([bad]).encode(), jobs, 'x')), 'VERIFICATION_FAILED')
        for data in (b'not json', b'{}', b'[]', b'[[]]'):
            with self.subTest(data=data):
                self.assertEqual(code_of(lambda: adaptor.observer_records(data, jobs, 'x')), 'VERIFICATION_FAILED')

    def test_raster_digest_validates_the_native_pnm_and_removes_it(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'e1.pnm'
            body = b'P6\n2 1\n255\n' + bytes(range(6))
            path.write_bytes(body)
            self.assertEqual(adaptor.pnm_digest(path, [2, 1]), hashlib.sha256(body).hexdigest())
            self.assertFalse(path.exists())
            for data, size in ((b'P5\n2 1\n255\n' + bytes(2), [2, 1]), (body, [3, 1]), (b'P6\n2 1\n255\n' + bytes(5), [2, 1]), (b'garbage', [1, 1])):
                path.write_bytes(data)
                self.assertEqual(code_of(lambda: adaptor.pnm_digest(path, size)), 'VERIFICATION_FAILED')
                self.assertFalse(path.exists())


class QpdfFixtures(unittest.TestCase):
    def test_committed_fixtures_match_the_independent_literal_builder(self):
        tool = load_tool('qualify_qpdf_fixtures')
        self.assertEqual((tool.FIXTURES / 'cover.pdf').read_bytes(), tool.cover())
        self.assertEqual((tool.FIXTURES / 'report.pdf').read_bytes(), tool.report())
        self.assertIn(b'/Rotate 90', tool.report())
        self.assertIn(b'/UserUnit 2', tool.report())
        self.assertIn(b'/CropBox [0 -20 144 124]', tool.report())

    def test_literal_expectations_apply_clockwise_turns_to_known_quadrants(self):
        tool = load_tool('qualify_qpdf_fixtures')
        self.assertEqual(tool.expected_page('cover', 1, 0)['size'], [298, 421])
        self.assertEqual(tool.expected_page('cover', 1, 90)['size'], [421, 298])
        upright = tool.expected_page('report', 3, 0)['quadrants']
        self.assertEqual(tool.expected_page('report', 3, 90)['quadrants'], [upright[2], upright[0], upright[3], upright[1]])
        self.assertEqual(tool.expected_page('report', 3, 180)['quadrants'], upright[::-1])

    def test_readiness_expectations_track_the_committed_fixtures(self):
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/qpdf/readiness.json').read_text())['routes'][adaptor.VERSION]['development']['cases']
        sizes = {'/sources/0/bytes': (ROOT / 'examples/schemaxis/fixtures/qpdf/cover.pdf').stat().st_size,
                 '/sources/1/bytes': (ROOT / 'examples/schemaxis/fixtures/qpdf/report.pdf').stat().st_size}
        recorded = {c['pointer']: c['expected'] for case in readiness for c in case['checks'] if c['file'] == 'capture.json'}
        self.assertEqual(recorded, sizes)

    def test_examples_plan_through_the_registry(self):
        from schemaxis.adaptors import registry
        for name, pages in (('qpdf-assemble', 5), ('qpdf-assemble-variant', 4)):
            self.assertEqual(len(registry.plan(json.loads((ROOT / 'examples/schemaxis' / (name + '.json')).read_text()))['pages']), pages)
        self.assertEqual(code_of(lambda: registry.plan(json.loads((ROOT / 'examples/schemaxis/qpdf-pages-invalid.json').read_text()))), 'INVALID_PDF_PAGES')


if __name__ == '__main__':
    unittest.main()
