"""Host tests of the EPUBCheck adaptor: planning, container preflight, run/verify lifecycle and tamper rejection.

A HOST-ONLY scripted launcher (``epubcheck_fake.py``) stands in for the native checker so these tests run anywhere; it is
not native evidence. ``test_epubcheck_native_boundary.py`` runs the official checker.
"""
import contextlib
import copy
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
from unittest import mock
from xml.etree import ElementTree
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
import epubcheck_fixture as fixture   # noqa: E402
from schemaxis.adaptors import registry   # noqa: E402
from schemaxis.adaptors.epubcheck import adaptor   # noqa: E402
from schemaxis.core.faults import SchemaxisError   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).with_name('epubcheck_fake.py')
NOTICE = 'Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=true\n'    # the JVM's own line; the host test launcher imitates it
FIXED_ENVIRONMENT = {'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=true'}
POISONED_ENVIRONMENT = {'JAVA_TOOL_OPTIONS': '-Xmx1k -Depubcheck.offline=false', 'JDK_JAVA_OPTIONS': '-Xmx1k', '_JAVA_OPTIONS': '-Xmx1k', 'SECRET_TOKEN': 'x'}


@contextlib.contextmanager
def private_configuration(locations=None):
    """A private SCHEMAXIS_CONFIG with SCHEMAXIS_EPUBCHECK cleared, so a machine's stored launcher cannot leak into a test."""
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
        path = Path(tmp) / 'private-config.json'
        path.write_text(json.dumps({'version': 1, 'locations': locations or {}}))
        os.environ['SCHEMAXIS_CONFIG'] = str(path)
        os.environ.pop('SCHEMAXIS_EPUBCHECK', None)
        yield


def scripted(**script):
    """A valid EPUB plus a FAKE.json member scripting the host-only launcher."""
    return fixture.with_member(fixture.valid(), 'FAKE.json', json.dumps(script))


def message(identifier='RSC-005', severity='ERROR', text='scripted finding', path='EPUB/package.opf'):
    return {'ID': identifier, 'severity': severity, 'message': text, 'additionalLocations': 0, 'suggestion': None,
            'locations': [{'url': {'opaque': False, 'hierarchical': True}, 'path': path, 'line': 3, 'column': 9, 'context': None}]}


def fault_code(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.code
    raise AssertionError('expected a fault')


def fault_message(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.message
    raise AssertionError('expected a fault')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.launcher = self.root / 'launcher'
        self.launcher.write_text('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, FAKE))
        self.launcher.chmod(0o755)
        self.counter = 0

    def source(self, data, name='book.epub'):
        self.counter += 1
        path = self.root / ('src%d' % self.counter) / name
        path.parent.mkdir()
        path.write_bytes(data)
        return str(path)

    def document(self, data):
        return {'version': adaptor.VERSION, 'operation': 'validate', 'source': self.source(data)}

    def run_epub(self, data, **options):
        self.counter += 1
        directory = self.root / ('out%d' % self.counter)
        options.setdefault('executable', str(self.launcher))
        options.setdefault('timeout', 60)
        adaptor.run(self.document(data), directory, **options)
        return directory

    def verify(self, directory):
        return adaptor.verify(directory, executable=str(self.launcher))

    def rejects(self, directory, code='VERIFICATION_FAILED'):
        self.assertEqual(fault_code(lambda: self.verify(directory)), code)

    def refresh(self, directory):
        """Recompute every receipt digest, as a forger who also fixes hashes would."""
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['artifacts'] = adaptor.publications(directory)
        receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
        (directory / 'verification.json').write_text(json.dumps(receipt))


class Planning(unittest.TestCase):
    def test_plan_is_native_free_and_never_reads_the_source(self):
        document = {'version': adaptor.VERSION, 'operation': 'validate', 'source': '/nonexistent/place/book.epub'}
        plan = adaptor.plan(document)
        self.assertEqual(plan['native']['arguments'][1:3], ['captured.epub', '--json'])
        self.assertIn('--failonwarnings', plan['native']['arguments'])
        self.assertEqual(plan['budget']['cpus'], 2)
        self.assertEqual(registry.plan(document)['version'], adaptor.PLAN_VERSION)
        self.assertEqual(adaptor.query(document), (['validate'], {}))

    def test_plan_states_the_offline_policy_honestly(self):
        native = adaptor.plan({'version': adaptor.VERSION, 'operation': 'validate', 'source': '/nonexistent/place/book.epub'})['native']
        self.assertEqual(native['environment'], {'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=true'})
        self.assertNotEqual(native['network'], 'none')
        self.assertIn('not an operating-system network boundary', native['network'])
        self.assertEqual(adaptor.NATIVE_ENVIRONMENT, FIXED_ENVIRONMENT)
        self.assertEqual(adaptor.OFFLINE_NOTICE, NOTICE)
        limits = ' '.join(adaptor.LOSSES)
        self.assertIn('not an operating-system network boundary', limits)
        self.assertIn('-Depubcheck.offline=true', limits)
        self.assertNotIn('not scanned by the host', limits)             # review 38: the old extension-only claim is gone
        for stated in ('under any file name', 'declared media type is XML', 'jar:http:', 'sets no memory limit', '14 of the 15', 'non-ASCII member names without the ZIP UTF-8 flag'):
            self.assertIn(stated, limits)

    def test_invalid_inputs_are_exact_faults(self):
        good = {'version': adaptor.VERSION, 'operation': 'validate', 'source': '/abs/book.epub'}
        for source in ('relative/book.epub', 'https://example.org/book.epub', '/abs/book.zip', '/abs/book.epub\0', '/abs/dir', 'file:///abs/book.epub'):
            self.assertEqual(fault_code(lambda: adaptor.plan({**good, 'source': source})), 'INVALID_EPUB_SOURCE', source)
        self.assertEqual(fault_code(lambda: adaptor.plan({**good, 'operation': 'repair'})), 'UNKNOWN_FILTER')
        self.assertEqual(fault_code(lambda: adaptor.plan({**good, 'version': 'schemaxis.epubcheck/2'})), 'UNSUPPORTED_VERSION')
        for key in ('profile', 'flags', 'java', 'failOnWarnings', 'severity'):
            self.assertEqual(fault_code(lambda: adaptor.plan({**good, key: 'x'})), 'UNKNOWN_ARGUMENT', key)
        self.assertEqual(fault_code(lambda: adaptor.plan({k: v for k, v in good.items() if k != 'source'})), 'MISSING_ARGUMENT')

    def test_schema_and_resources(self):
        schema = adaptor.schema()
        self.assertEqual(set(schema['properties']), {'version', 'operation', 'source'})
        self.assertEqual(adaptor.resources({}, {}, 'job'), {'threads': 2})
        self.assertEqual(adaptor.resources({}, {'threads': 1}, 'job'), {'threads': 1})
        for threads in (3, 0, True):
            self.assertEqual(fault_code(lambda: adaptor.resources({}, {'threads': threads}, 'job')), 'INVALID_EXECUTION')

    def test_adaptor_never_imports_another_adaptor_or_the_native_application(self):
        text = (ROOT / 'src/schemaxis/adaptors/epubcheck/adaptor.py').read_text()
        self.assertNotIn('schemaxis.adaptors.', text.replace('schemaxis.adaptors.epubcheck', ''))
        self.assertEqual(adaptor.runtime.__module__, adaptor.__name__)

    def test_capabilities_and_search_cases_use_real_search(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        self.assertTrue(check_cases(CapabilityCatalogue(), 'epubcheck')['complete'])

    def test_reusable_inputs_bind_the_captured_digest_and_refuse_bad_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'book.epub'
            path.write_bytes(fixture.valid())
            document = {'version': adaptor.VERSION, 'operation': 'validate', 'source': str(path)}
            self.assertEqual(adaptor.reusableInputs(document), {str(path): hashlib.sha256(fixture.valid()).hexdigest()})
            path.write_bytes(b'not a zip')
            self.assertEqual(fault_code(lambda: adaptor.reusableInputs(document)), 'INVALID_EPUB_ARCHIVE')


class Preflight(unittest.TestCase):
    def refused(self, data, code):
        self.assertEqual(fault_code(lambda: adaptor.preflight(data)), code)

    def test_valid_packages_are_measured(self):
        facts = adaptor.preflight(fixture.valid())
        self.assertEqual(sorted(m['name'] for m in facts['members']),
                         ['EPUB/chapter.xhtml', 'EPUB/nav.xhtml', 'EPUB/package.opf', 'META-INF/container.xml', 'mimetype'])
        self.assertEqual(facts['uncompressedBytes'], sum(m['uncompressed'] for m in facts['members']))
        self.assertEqual(adaptor.preflight(fixture.rich())['directories'], 0)

    def test_not_a_zip_and_damaged_zips(self):
        self.refused(b'hello', 'INVALID_EPUB_ARCHIVE')
        self.refused(fixture.valid()[:-30], 'INVALID_EPUB_ARCHIVE')
        self.refused(b'PK\x03\x04' + b'\0' * 60, 'INVALID_EPUB_ARCHIVE')
        damaged = bytearray(fixture.package([('mimetype', 'application/epub+zip', False)]))
        damaged[40] ^= 0xff    # a stored byte: the CRC no longer matches
        self.refused(bytes(damaged), 'INVALID_EPUB_ARCHIVE')

    def test_unsafe_names_links_and_collisions(self):
        def entry(name, data=b'x', flags=0, external=0o100644 << 16, system=3):
            return (name, data, flags, external, system)
        for name in (b'../evil', b'/abs', b'a/../b', b'a\\b', b'C:evil', b'a//b', b'./a', b'a\x01b', b''):
            self.refused(fixture.raw_zip([entry(name)]), 'UNSAFE_EPUB_ARCHIVE')
        self.refused(fixture.raw_zip([entry(b'a'), entry(b'a')]), 'UNSAFE_EPUB_ARCHIVE')
        self.refused(fixture.raw_zip([entry(b'Book.xhtml'), entry(b'book.XHTML')]), 'UNSAFE_EPUB_ARCHIVE')
        self.refused(fixture.raw_zip([entry(b'link', b'target', external=0o120777 << 16)]), 'UNSAFE_EPUB_ARCHIVE')
        self.refused(fixture.raw_zip([entry(b'fifo', external=0o010644 << 16)]), 'UNSAFE_EPUB_ARCHIVE')
        self.refused(fixture.raw_zip([entry(b'secret', flags=1)]), 'UNSUPPORTED_EPUB_FEATURE')

    def test_unsupported_compression(self):
        import io
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(zipfile.ZipInfo('a.bin'), b'x' * 100, zipfile.ZIP_BZIP2)
        self.refused(buffer.getvalue(), 'UNSUPPORTED_EPUB_FEATURE')

    def test_entities_dtds_and_utf16(self):
        base = fixture.valid()
        entity = '<?xml version="1.0"?><!DOCTYPE html [<!ENTITY x "y">]><html xmlns="http://www.w3.org/1999/xhtml"/>'
        for text in (entity, '<!DOCTYPE html [ ]><html/>', '<!DOCTYPE html SYSTEM "http://evil.example/x.dtd"><html/>',
                     '<!DOCTYPE html SYSTEM "x.dtd"><html/>', '<!DOCTYPE html SYSTEM "file:///etc/passwd"><html/>'):
            self.refused(fixture.with_member(base, 'EPUB/x.xhtml', text), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/y.xhtml', '﻿' + entity.replace('<!ENTITY', '<!ENTITY').encode('utf-16').decode('utf-16')), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/z.xml', entity.encode('utf-16')), 'UNSUPPORTED_EPUB_FEATURE')
        for allowed in ('<!DOCTYPE html>', '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'):
            adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xhtml', allowed + '<html xmlns="http://www.w3.org/1999/xhtml"/>'))
        self.refused(fixture.with_member(base, 'EPUB/data.bin', '<!ENTITY inert in an extension-less binary member>'), 'UNSUPPORTED_EPUB_FEATURE')   # review 38: no extension bypass

    def test_xml_encoding_profile_is_utf8_or_marked_utf16_only(self):
        base = fixture.valid()
        body = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body><p>é</p></body></html>'
        entity = '<!DOCTYPE html [<!ENTITY x "y">]>' + body
        for encoding in ('utf-32', 'utf-32-le', 'utf-32-be'):
            self.refused(fixture.with_member(base, 'EPUB/a.xhtml', ('<?xml version="1.0"?>' + body).encode(encoding)), 'UNSUPPORTED_EPUB_FEATURE')
            self.refused(fixture.with_member(base, 'EPUB/a.xhtml', ('<?xml version="1.0"?>' + entity).encode(encoding)), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', b'\xff\xfe\x00\x00' + body.encode('utf-16-le')), 'UNSUPPORTED_EPUB_FEATURE')
        for encoding in ('utf-16-le', 'utf-16-be'):         # no byte-order mark, with and without a leading space
            for lead in ('', ' ', '\n'):
                self.refused(fixture.with_member(base, 'EPUB/a.xhtml', (lead + entity).encode(encoding)), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', b'<html>\x00</html>'), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', b'<html>\xff\xfe</html>'), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', b'\xef\xbb\xbf<html>\xc3</html>'), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', ('<?xml version="1.0"?>' + body).encode('utf-16')[:-1]), 'UNSUPPORTED_EPUB_FEATURE')   # odd length
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', b'\xff\xfe' + b'\x00\xd8<\x00'), 'UNSUPPORTED_EPUB_FEATURE')                     # lone surrogate
        for declared in ('ISO-8859-1', 'UTF-7', 'US-ASCII', 'EBCDIC-CP-US', 'UTF-16', 'UTF-32', 'x'):
            self.refused(fixture.with_member(base, 'EPUB/a.xhtml', '<?xml version="1.0" encoding="%s"?>%s' % (declared, body)), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', ('<?xml version="1.0" encoding="UTF-8"?>' + body).encode('utf-16')), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/a.xhtml', ('<?xml version="1.0" encoding="UTF-16LE"?>' + body).encode('utf-16')), 'UNSUPPORTED_EPUB_FEATURE')
        for text in ('<?xml version="1.0"?>' + body, "<?xml version='1.0' encoding='utf-8'?>" + body, '<?xml version="1.0" encoding="UTF-8"?>' + body, body):
            adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xhtml', text))
            adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xhtml', b'\xef\xbb\xbf' + text.encode()))
        adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xml', ('<?xml version="1.0" encoding="UTF-16"?>' + body).encode('utf-16')))
        adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xml', b'\xfe\xff' + ('<?xml version="1.0"?>' + body).encode('utf-16-be')))

    def test_doctype_system_identifiers_must_be_in_the_checker_catalogue(self):
        base = fixture.valid()
        html = '<html xmlns="http://www.w3.org/1999/xhtml"/>'
        self.assertEqual(len(adaptor.CATALOGUE_DTDS), 15)
        self.assertIsInstance(adaptor.CATALOGUE_DTDS, frozenset)
        self.assertFalse(any(prefix in adaptor.CATALOGUE_DTDS for prefix in ('http://www.w3.org/', 'http://www.daisy.org/', 'http://www.idpf.org/', 'http://openebook.org/')))
        for identifier in sorted(adaptor.CATALOGUE_DTDS):
            for form in ('<!DOCTYPE html PUBLIC "-//X//DTD X//EN" "%s">', "<!DOCTYPE html PUBLIC '-//X//DTD X//EN' '%s'>", '<!DOCTYPE html SYSTEM "%s">', '<!DOCTYPE html\n  SYSTEM\t"%s"  >'):
                adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xhtml', (form % identifier) + html))
        for refused in ('http://www.w3.org/TR/html4/loose.dtd', 'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd ', 'http://www.w3.org/TR/xhtml11/DTD/XHTML11.dtd',
                        'https://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd', 'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd?x=1', 'http://www.w3.org/', 'http://www.daisy.org/other.dtd',
                        'http://www.idpf.org/dtds/2007/other.dtd', 'http://openebook.org/', 'http://127.0.0.1:9/x.dtd', 'http://127.0.0.1:9/', 'file:///etc/hostname',
                        '/etc/hostname', 'x.dtd', 'x', '', 'xhtml-lat1.ent', 'about:legacy-compat/', 'ABOUT:LEGACY-COMPAT', 'ftp://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'):
            self.refused(fixture.with_member(base, 'EPUB/x.xhtml', '<!DOCTYPE html PUBLIC "-//SCHEMAXIS//DTD CANARY//EN" "%s">%s' % (refused, html)), 'UNSUPPORTED_EPUB_FEATURE')
            self.refused(fixture.with_member(base, 'EPUB/x.opf', '<!DOCTYPE html SYSTEM "%s">%s' % (refused, html)), 'UNSUPPORTED_EPUB_FEATURE')
        for form in ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN">', '<!doctype html>', '<!DOCTYPE>', '<!DOCTYPE html SYSTEM>', '<!DOCTYPE html SYSTEM "about:legacy-compat" "x">',
                     '<!DOCTYPE html [<!ELEMENT html ANY>]>', '<!DOCTYPE html SYSTEM "about:legacy-compat" [ ]>', '<!DOCTYPE html system "about:legacy-compat">',
                     '<!DOCTYPE html SYSTEM "about:legacy-compat', '<!DOCTYPE html SYSTEM "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd>"', '<!DOCTYPE html%SYSTEM "about:legacy-compat">'):
            self.refused(fixture.with_member(base, 'EPUB/x.xhtml', form + html), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/x.xhtml', '<!-- <!DOCTYPE html SYSTEM "x"> -->' + html), 'UNSUPPORTED_EPUB_FEATURE')     # conservative: comments are not parsed
        self.refused(fixture.with_member(base, 'EPUB/x.xhtml', '<!DOCTYPE html>' + html + '<!DOCTYPE html SYSTEM "file:///etc/hostname">'), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.with_member(base, 'EPUB/x.xml', ('<!DOCTYPE html SYSTEM "file:///etc/hostname">' + html).encode('utf-16')), 'UNSUPPORTED_EPUB_FEATURE')
        adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xhtml', '<!DOCTYPE html>' + html))
        adaptor.preflight(fixture.with_member(base, 'EPUB/ok.xml', ('<!DOCTYPE html SYSTEM "about:legacy-compat">' + html).encode('utf-16')))

    def test_budgets(self):
        base = fixture.valid()
        self.refused(fixture.with_member(base, 'EPUB/zeros.bin', bytes(2 * 1024 * 1024)), 'EPUB_BUDGET')     # expansion ratio
        with mock.patch.object(adaptor, 'MAX_MEMBERS', 5):
            self.refused(fixture.with_member(base, 'EPUB/extra.txt', 'x'), 'EPUB_BUDGET')
        with mock.patch.object(adaptor, 'MAX_MEMBER_BYTES', 100):
            self.refused(base, 'EPUB_BUDGET')
        with mock.patch.object(adaptor, 'MAX_UNCOMPRESSED_BYTES', 1000):
            self.refused(base, 'EPUB_BUDGET')
        with mock.patch.object(adaptor, 'MAX_EPUB_BYTES', len(base) - 1):
            self.refused(base, 'EPUB_BUDGET')
        self.assertEqual(fault_code(lambda: adaptor.preflight(base[:3])), 'INVALID_EPUB_ARCHIVE')


    # ---- review 38: the checker parses by declared role and media type, not by file extension
    def package_with(self, name, content, media_type='application/xhtml+xml', opf_name='EPUB/package.opf', reference=None):
        """The valid EPUB 3 with one more manifest item ``name`` whose declared media type makes the checker parse it as XML."""
        base = opf_name.rpartition('/')[0]
        href = reference or (name[len(base) + 1:] if base and name.startswith(base + '/') else name)
        opf = fixture.opf(extra='<item id="extra" href="%s" media-type="%s"/>' % (href, media_type))
        container = fixture.CONTAINER.replace('EPUB/package.opf', opf_name)
        members = [('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', container, True), (opf_name, opf, True),
                   ('EPUB/nav.xhtml', fixture.NAV, True), ('EPUB/chapter.xhtml', fixture.chapter(), True), (name, content, True)]
        return fixture.package(members)

    def test_manifest_declared_xml_is_gated_whatever_the_extension(self):
        html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body/></html>'
        hostile = ('<!DOCTYPE html SYSTEM "file:///etc/hostname">', '<!DOCTYPE html SYSTEM "jar:http://127.0.0.1:9/x.jar!/x.dtd">',
                   '<!DOCTYPE html SYSTEM "ftp://127.0.0.1:9/x.dtd">', '<!DOCTYPE html PUBLIC "-//X//DTD X//EN" "http://127.0.0.1:9/x.dtd">',
                   '<!DOCTYPE html [<!ENTITY x SYSTEM "file:///etc/hostname">]>')
        for name in ('EPUB/c.txt', 'EPUB/c.bin', 'EPUB/c', 'EPUB/c.dat', 'EPUB/sub/c.XHTMLX'):
            for doctype in hostile:
                self.refused(self.package_with(name, doctype + html), 'UNSUPPORTED_EPUB_FEATURE')
        for media_type in ('application/xhtml+xml', 'image/svg+xml', 'application/x-dtbncx+xml', 'application/smil+xml', 'text/html', 'application/xml', 'application/vnd.x+xml',
                           'Application/XHTML+XML ; charset=utf-8'):
            self.refused(self.package_with('EPUB/c.bin', hostile[0] + html, media_type), 'UNSUPPORTED_EPUB_FEATURE')
        for reference in ('c%2Ebin', './c.bin', 'c.bin#frag', 'c.bin?x=1', 'x/../c.bin', '../EPUB/c.bin'):      # percent-encoded, dotted, fragment, query and parent forms
            self.refused(self.package_with('EPUB/c.bin', hostile[0] + html, reference=reference), 'UNSUPPORTED_EPUB_FEATURE')
        adaptor.preflight(self.package_with('EPUB/c.bin', html))                                  # control: a conforming XML member under a non-XML name is accepted
        adaptor.preflight(self.package_with('EPUB/c.bin', b'\x00\x01 not xml', 'image/png'))      # control: the same bytes are fine when the manifest does not declare XML

    def test_manifest_xml_must_meet_the_strict_encoding_profile_under_any_name(self):
        body = '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body/></html>'
        for label, data in (('utf32', body.encode('utf-32')), ('utf32le', body.encode('utf-32-le')), ('utf32be-doctype', ('<!DOCTYPE html SYSTEM "file:///x">' + body).encode('utf-32-be')),
                            ('ebcdic', body.encode('cp037')), ('ebcdic-doctype', ('<!DOCTYPE html SYSTEM "file:///x">' + body).encode('cp037')),
                            ('latin1-declared', body.replace('?>', ' encoding="ISO-8859-1"?>', 1).encode()), ('utf7-declared', body.replace('?>', ' encoding="UTF-7"?>', 1).encode()),
                            ('utf16-no-bom', body.encode('utf-16-le')), ('utf16-be-no-bom', body.encode('utf-16-be')), ('nul', body.encode() + b'\x00')):
            for name in ('EPUB/c.txt', 'EPUB/c.bin', 'EPUB/c'):
                with self.subTest(label=label, name=name):
                    self.refused(self.package_with(name, data), 'UNSUPPORTED_EPUB_FEATURE')
        adaptor.preflight(self.package_with('EPUB/c.txt', body.encode('utf-16')))
        adaptor.preflight(self.package_with('EPUB/c.txt', b'\xef\xbb\xbf' + body.encode()))

    def test_nonstandard_package_name_is_found_from_the_container_rootfile(self):
        html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body/></html>'
        hostile = '<!DOCTYPE html SYSTEM "file:///etc/hostname">' + html
        for opf_name in ('EPUB/package.dat', 'OEBPS/content', 'pkg.bin'):
            base = opf_name.rpartition('/')[0]
            member = (base + '/' if base else '') + 'c.txt'
            data = self.package_with(member, hostile, opf_name=opf_name)
            self.refused(data, 'UNSUPPORTED_EPUB_FEATURE')
            adaptor.preflight(self.package_with(member, html, opf_name=opf_name))
        # the package document itself is held to the profile, and a package or container the host cannot parse is refused rather than skipped
        self.refused(fixture.package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', fixture.CONTAINER.replace('EPUB/package.opf', 'p.bin'), True),
                                      ('p.bin', '<!DOCTYPE package SYSTEM "file:///etc/hostname"><package/>', True)]), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', fixture.CONTAINER, True),
                                      ('EPUB/package.opf', '<package xmlns="http://www.idpf.org/2007/opf"><manifest>', True)]), 'UNSUPPORTED_EPUB_FEATURE')
        self.refused(fixture.package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', '<container>', True)]), 'UNSUPPORTED_EPUB_FEATURE')
        adaptor.preflight(fixture.package([('mimetype', 'application/epub+zip', False)]))      # no container at all: nothing to index; the checker reports it

    def test_content_markers_hold_any_member_to_the_strict_profile(self):
        base = fixture.valid()
        doctype = '<!DOCTYPE html SYSTEM "file:///etc/hostname">'
        entity = '<!ENTITY x "y">'
        for name in ('EPUB/a.bin', 'EPUB/b.txt', 'EPUB/css/style.css', 'EPUB/noext', 'EPUB/img/p.png'):
            for text in (doctype, entity, doctype.lower(), entity.upper()):
                for codec in ('utf-8', 'utf-16-le', 'utf-16-be', 'utf-16'):
                    with self.subTest(name=name, text=text, codec=codec):
                        self.refused(fixture.with_member(base, name, b'\x01\x02' + text.encode(codec)), 'UNSUPPORTED_EPUB_FEATURE')
        for text in (doctype, entity):
            for codec in ('utf-32-le', 'utf-32-be', 'utf-32'):
                self.refused(fixture.with_member(base, 'EPUB/a.bin', b'junk' + text.encode(codec)), 'UNSUPPORTED_EPUB_FEATURE')
        for member in (b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 4, 'body { color: red }'.encode(), '<p>no marker</p>'.encode('utf-16')):
            adaptor.preflight(fixture.with_member(base, 'EPUB/ok.bin', member))            # controls: binary and marker-free text pass untouched
        adaptor.preflight(fixture.with_member(base, 'EPUB/ok.txt', '<!DOCTYPE html>'))      # a plain DOCTYPE passes the same profile as in XML members

    # ---- review 43: the unlisted-member backstop holds whatever the role index finds
    def test_unlisted_members_that_look_like_xml_are_held_to_the_profile_in_any_encoding(self):
        base = fixture.valid()
        html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body/></html>'
        doctype = '<!DOCTYPE html SYSTEM "file:///etc/hostname">' + html
        declaration = '<?xml version="1.0"?>'
        cases = (
            ('cp037-signature', (declaration + doctype).encode('cp037')),                                    # literal EBCDIC '<?xm' signature form (4c 6f a7 94)
            ('cp037-signature-bare', declaration.encode('cp037') + b'junk'),
            ('cp500-signature', (declaration + doctype).encode('cp500')),
            ('ascii-declares-ibm037', b'<?xml version="1.0" encoding="IBM037"?>' + doctype.encode('cp037')),   # ASCII declaration, then EBCDIC text
            ('ascii-declares-cp037', b'<?xml version="1.0" encoding="cp037"?>' + doctype.encode('cp037')),
            ('ascii-declares-ibm037-plain', ('<?xml version="1.0" encoding="IBM037"?>' + doctype).encode()),
            ('ucs4-2143-at-0', b''.join(b'\x00\x00' + c.encode() + b'\x00' for c in declaration + doctype)),   # UCS-4 byte order 2143 from offset 0
            ('ucs4-3412-at-0', b''.join(b'\x00' + c.encode() + b'\x00\x00' for c in declaration + doctype)),
            ('ucs4-1234', (declaration + doctype).encode('utf-32-be')),
            ('ucs4-4321', (declaration + doctype).encode('utf-32-le')),
            ('utf32-mark-then-junk', b'\xff\xfe\x00\x00' + b'\x80' * 8),
            ('mixed-order-mark', b'\xfe\xff\x00\x00' + b'\x80' * 8),
            ('utf8-bom-other-encoding', b'\xef\xbb\xbf<?xml version="1.0" encoding="ISO-8859-1"?>' + doctype.encode()),
            ('utf8-bom-ibm037', b'\xef\xbb\xbf<?xml version="1.0" encoding="IBM037"?>' + doctype.encode('cp037')),
            ('uppercase-declaration', b'<?XML version="1.0" encoding="UTF-7"?>' + doctype.encode()),
            ('declared-utf16-on-utf8', ('<?xml version="1.0" encoding="UTF-16"?>' + html).encode()),
            ('plain-hostile-doctype', (declaration + doctype).encode()),
            ('utf8-bom-hostile-doctype', b'\xef\xbb\xbf' + (declaration + doctype).encode()))
        for name in ('EPUB/c.bin', 'EPUB/c', 'EPUB/css/c.dat', 'c.txt'):
            for label, data in cases:
                with self.subTest(name=name, label=label):
                    self.refused(fixture.with_member(base, name, data), 'UNSUPPORTED_EPUB_FEATURE')
        for label, data in (('plain-xml-bin', (declaration + html).encode()), ('bom-xml-bin', b'\xef\xbb\xbf' + (declaration + html).encode()),
                            ('declared-utf8', ('<?xml version="1.0" encoding="UTF-8"?>' + html).encode()), ('plain-doctype', ('<!DOCTYPE html>' + html).encode()),
                            ('utf16-bom-xml', (declaration + html).encode('utf-16')), ('uppercase-declaration', ('<?XML version="1.0"?>' + html).encode())):
            with self.subTest(control=label):
                adaptor.preflight(fixture.with_member(base, 'EPUB/ok.bin', data))          # controls: valid UTF-8 (or marked UTF-16) XML under a binary name is accepted

    def test_ambiguous_references_in_the_index_are_refused_before_java(self):
        html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body/></html>'
        for label, reference in (('backslash', 'sub\\c.bin'), ('tab', 'c&#9;.bin'), ('lf', 'c&#10;.bin'), ('cr', 'c&#13;.bin'), ('c0', 'c&#1;.bin'), ('del', 'c&#127;.bin'),
                                 ('leading-tab', '&#9;c.bin'), ('backslash-ref', 'a&#92;b')):
            with self.subTest(href=label):
                self.refused(self.package_with('EPUB/c.bin', html, reference=reference), 'UNSUPPORTED_EPUB_FEATURE')
        # the same characters in an href of a manifest item that is not declared XML do not matter to the index, so they are not refused here
        opf = fixture.opf(extra='<item id="extra" href="sub\\c.bin" media-type="image/png"/>')
        adaptor.preflight(fixture.package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', fixture.CONTAINER, True), ('EPUB/package.opf', opf, True),
                                           ('EPUB/nav.xhtml', fixture.NAV, True), ('EPUB/chapter.xhtml', fixture.chapter(), True)]))
        for label, path in (('backslash', 'EPUB\\package.opf'), ('tab', 'EPUB/package&#9;.opf'), ('lf', 'EPUB/package&#10;.opf'), ('del', 'EPUB/package&#127;.opf')):
            with self.subTest(full_path=label):
                container = fixture.CONTAINER.replace('EPUB/package.opf', path)
                self.refused(fixture.package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', container, True), ('EPUB/package.opf', fixture.opf(), True),
                                              ('EPUB/nav.xhtml', fixture.NAV, True), ('EPUB/chapter.xhtml', fixture.chapter(), True)]), 'UNSUPPORTED_EPUB_FEATURE')
        adaptor.preflight(self.package_with('EPUB/sub/c.bin', html, reference='sub/c.bin'))    # control: an ordinary relative reference is accepted

    def test_duplicate_rootfiles_parse_each_package_once(self):
        """Strict constants, not wall-clock: the number of scan_xml calls does not grow with the number of rootfile elements."""
        def counted(container):
            book = fixture.package([('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', container, True), ('EPUB/package.opf', fixture.opf(), True),
                                    ('EPUB/nav.xhtml', fixture.NAV, True), ('EPUB/chapter.xhtml', fixture.chapter(), True)])
            real, names = adaptor.scan_xml, []
            with mock.patch.object(adaptor, 'scan_xml', side_effect=lambda name, data, location: (names.append(name), real(name, data, location))[1]):
                adaptor.preflight(book)
            return names
        rootfile = '<rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>'
        single = counted(fixture.CONTAINER)
        many = counted(fixture.CONTAINER.replace(rootfile, rootfile * 1000))
        self.assertEqual(sorted(many), sorted(single))
        self.assertLessEqual(many.count('EPUB/package.opf'), 2)        # once for the index, at most once more in the whole-container pass
        self.assertLessEqual(many.count('META-INF/container.xml'), 2)
        spelled = fixture.CONTAINER.replace(rootfile, ''.join('<rootfile full-path="%sEPUB/package.opf" media-type="application/oebps-package+xml"/>' % ('./' * (n % 3)) for n in range(300)))
        self.assertEqual(sorted(counted(spelled)), sorted(single))     # differently spelled references to one package are also parsed once

    # ---- care 52 memory repair: the role index reads container and package documents incrementally, so irrelevant elements neither cost a tree nor hide a role
    def padded_book(self, count, opf_name='EPUB/package.opf', member=None, content='', reference=None, media_type='application/xhtml+xml', manifest_extra='', container_extra='',
                    opf_tail='', stored=True):
        """The valid EPUB 3 whose container and package documents carry ``count`` irrelevant elements before and after every real rootfile and manifest item."""
        pad = '<a/>' * count
        base = opf_name.rpartition('/')[0]
        rootfile = '<rootfile full-path="%s" media-type="application/oebps-package+xml"/>' % opf_name
        container = fixture.CONTAINER.replace('EPUB/package.opf" media-type="application/oebps-package+xml"/>', opf_name + '" media-type="application/oebps-package+xml"/>')
        container = container.replace(rootfile, pad + rootfile + pad + container_extra)
        item = '<item id="extra" href="%s" media-type="%s"/>' % (reference or (member[len(base) + 1:] if base and member else member), media_type) if member else ''
        opf = fixture.opf(extra=pad + item + pad + manifest_extra).replace('</package>', opf_tail + '</package>')
        members = [('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', container, not stored), (opf_name, opf, not stored),
                   ('EPUB/nav.xhtml', fixture.NAV, True), ('EPUB/chapter.xhtml', fixture.chapter(), True)]
        if member:
            members.append((member, content, True))
        return fixture.package(members)

    def role_index(self, book):
        with zipfile.ZipFile(io.BytesIO(book)) as archive:
            return adaptor.xml_member_names(archive.read, {info.filename for info in archive.infolist() if not info.is_dir()}, '$.source')

    def test_irrelevant_elements_do_not_hide_a_role_from_the_incremental_index(self):
        html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body/></html>'
        hostile = '<!DOCTYPE html SYSTEM "file:///etc/hostname">' + html
        for opf_name, member in (('EPUB/package.opf', 'EPUB/c.bin'), ('EPUB/package.dat', 'EPUB/c.bin'), ('OEBPS/content', 'OEBPS/c.txt'), ('pkg.bin', 'c.bin')):
            with self.subTest(package=opf_name):
                small = self.role_index(self.padded_book(0, opf_name, member, html))
                many = self.role_index(self.padded_book(20000, opf_name, member, html))
                self.assertEqual(small, {opf_name, member} | ({'EPUB/nav.xhtml', 'EPUB/chapter.xhtml'} if opf_name.startswith('EPUB/') else set()))
                self.assertEqual(many, small)                                       # the same exact role index with 160000 irrelevant elements around the real items
                adaptor.preflight(self.padded_book(20000, opf_name, member, html))   # control: a conforming XML member under an unlisted name is accepted
                self.refused(self.padded_book(20000, opf_name, member, hostile), 'UNSUPPORTED_EPUB_FEATURE')      # the DOCTYPE behind the padding is still found
        self.assertEqual(self.role_index(self.padded_book(20000, member='EPUB/c.bin', content=b'\x89PNG', media_type='image/png')),
                         {'EPUB/package.opf', 'EPUB/nav.xhtml', 'EPUB/chapter.xhtml'})      # a non-XML item stays unindexed
        for media_type in ('application/xhtml+xml', 'image/svg+xml'):
            self.refused(self.padded_book(20000, member='EPUB/c.bin', content=hostile, media_type=media_type), 'UNSUPPORTED_EPUB_FEATURE')

    def test_ambiguous_references_and_malformed_tails_are_found_after_many_irrelevant_elements(self):
        html = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body/></html>'
        for count in (0, 20000):
            with self.subTest(count=count):
                for reference in ('sub\\c.bin', 'c&#9;.bin', 'c&#127;.bin'):
                    text = fault_message(lambda: adaptor.preflight(self.padded_book(count, member='EPUB/c.bin', content=html, reference=reference)))
                    self.assertIn('manifest href', text)
                    self.assertIn('backslash or a control character', text)
                    self.assertLess(len(text), 400)
                text = fault_message(lambda: adaptor.preflight(self.padded_book(count, container_extra='<rootfile full-path="EPUB/p&#9;.opf" media-type="x"/>')))
                self.assertIn('rootfile full-path', text)
                for label, tail in (('unclosed', '<late>'), ('junk', '&'), ('undefined-entity', '<m>&bogus;</m>'), ('second-root', '<other/>')):
                    book = self.padded_book(count, opf_tail=tail if label != 'second-root' else '', member='EPUB/c.bin', content=html)
                    if label == 'second-root':
                        book = self.padded_book(count, member='EPUB/c.bin', content=html, manifest_extra='')
                        with zipfile.ZipFile(io.BytesIO(book)) as archive:
                            members = [(i.filename, archive.read(i), i.compress_type != zipfile.ZIP_STORED or i.filename != 'mimetype') for i in archive.infolist()]
                        members = [(n, d + b'<other/>' if n == 'EPUB/package.opf' else d, c) for n, d, c in members]
                        book = fixture.package(members)
                    with self.subTest(late=label):
                        self.assertIn('not well-formed XML', fault_message(lambda: adaptor.preflight(book)))
                        self.assertEqual(fault_code(lambda: self.role_index(book)), 'UNSUPPORTED_EPUB_FEATURE')
                # a malformed tail wins over an ambiguity seen earlier in the same document, exactly as with a whole-document parse
                book = self.padded_book(count, member='EPUB/c.bin', content=html, reference='sub\\c.bin', opf_tail='<late>')
                self.assertIn('not well-formed XML', fault_message(lambda: adaptor.preflight(book)))
                container = self.padded_book(count, container_extra='<rootfile full-path="a&#9;b" media-type="x"/><late>')
                self.assertIn('not well-formed XML', fault_message(lambda: adaptor.preflight(container)))
                adaptor.preflight(self.padded_book(count, member='EPUB/c.bin', content=html))      # control: the same padded book without a fault is accepted

    def test_many_distinct_rootfile_spellings_still_find_every_package_once(self):
        """More distinct spellings than the bounded memo remembers: resolution repeats cheaply, the set of packages and the scan counts do not change."""
        second = fixture.opf(title='Second', extra='<item id="x" href="x.bin" media-type="application/xhtml+xml"/>')
        spellings = ''.join('<rootfile full-path="d%d/../EPUB/package.opf" media-type="application/oebps-package+xml"/>' % n for n in range(4300))
        container = fixture.CONTAINER.replace('</rootfiles>', spellings + '<rootfile full-path="EPUB/second.opf" media-type="application/oebps-package+xml"/>'
                                              + spellings + '</rootfiles>')
        members = [('mimetype', 'application/epub+zip', False), ('META-INF/container.xml', container, True), ('EPUB/package.opf', fixture.opf(), True),
                   ('EPUB/second.opf', second, True), ('EPUB/x.bin', '<html xmlns="http://www.w3.org/1999/xhtml"/>', True), ('EPUB/nav.xhtml', fixture.NAV, True),
                   ('EPUB/chapter.xhtml', fixture.chapter(), True)]
        book = fixture.package(members)
        self.assertEqual(self.role_index(book), {'EPUB/package.opf', 'EPUB/second.opf', 'EPUB/x.bin', 'EPUB/nav.xhtml', 'EPUB/chapter.xhtml'})
        real, names = adaptor.scan_xml, []
        with mock.patch.object(adaptor, 'scan_xml', side_effect=lambda name, data, location: (names.append(name), real(name, data, location))[1]):
            adaptor.preflight(book)
        for package in ('EPUB/package.opf', 'EPUB/second.opf', 'META-INF/container.xml'):
            self.assertLessEqual(names.count(package), 2)
        self.assertLess(adaptor.MAX_INDEX_MEMO, 4300)             # the spellings really do exceed the memo

    def test_index_memory_does_not_grow_with_the_element_count(self):
        """Measured with tracemalloc on ~1 MiB documents (never the 32 MiB advertised ceiling): a whole-document parse retains tens of MiB for these
        sibling elements; the incremental index stays within a few input-sizes. Old/new ratios are measured live, so the test says what a tree would cost."""
        count = 1 << 18
        pad = '<a/>' * count
        container = fixture.CONTAINER.replace('</rootfiles>', pad + '</rootfiles>').encode()
        opf = fixture.opf(extra=pad + '<item id="x" href="x.bin" media-type="application/xhtml+xml"/>').encode()
        self.assertGreater(len(container), 1 << 20)
        members = {'META-INF/container.xml': container, 'EPUB/package.opf': opf, 'EPUB/x.bin': b'<html xmlns="http://www.w3.org/1999/xhtml"/>'}

        def peak(action):
            gc.collect()
            tracemalloc.start()
            try:
                base = tracemalloc.get_traced_memory()[0]
                tracemalloc.reset_peak()
                action()
                return tracemalloc.get_traced_memory()[1] - base
            finally:
                tracemalloc.stop()
        found = []
        incremental = peak(lambda: found.append(adaptor.xml_member_names(members.__getitem__, set(members), '$.source')))
        self.assertEqual(found[0], {'EPUB/package.opf', 'EPUB/x.bin'})
        wholetree = peak(lambda: sum(1 for _ in ElementTree.fromstring(container.decode()).iter()))
        self.assertLess(incremental, 5 * len(container))             # the bytes and decoded text of one document plus a chunk, not an element per sibling
        self.assertGreater(wholetree, 8 * incremental)                # the tree this replaces retained far more for the same document
        # a fault after 262144 irrelevant elements leaves no retained parser state or text behind
        broken = dict(members, **{'EPUB/package.opf': opf.replace(b'</package>', b'<late></package>')})
        self.assertEqual(fault_code(lambda: adaptor.xml_member_names(broken.__getitem__, set(broken), '$.source')), 'UNSUPPORTED_EPUB_FEATURE')
        gc.collect()
        tracemalloc.start()
        try:
            base = tracemalloc.get_traced_memory()[0]
            fault_code(lambda: adaptor.xml_member_names(broken.__getitem__, set(broken), '$.source'))
            gc.collect()
            self.assertLess(tracemalloc.get_traced_memory()[0] - base, 1 << 18)
        finally:
            tracemalloc.stop()

    def test_a_nul_in_a_zip_member_name_is_refused_not_truncated(self):
        def entry(name):
            return (name, b'<html/>', 0, 0o100644 << 16, 3)
        both = fixture.raw_zip([entry(b'EPUB/c\x00.xhtml')])                    # central and local names both carry the NUL
        self.refused(both, 'UNSAFE_EPUB_ARCHIVE')
        marked = fixture.raw_zip([entry(b'EPUB/cX.xhtml')])
        first, last = marked.index(b'cX'), marked.rindex(b'cX')
        central_only = marked[:last] + b'c\x00' + marked[last + 2:]
        local_only = marked[:first] + b'c\x00' + marked[first + 2:]
        self.refused(central_only, 'UNSAFE_EPUB_ARCHIVE')
        self.assertIn(fault_code(lambda: adaptor.preflight(local_only)), ('INVALID_EPUB_ARCHIVE', 'UNSAFE_EPUB_ARCHIVE'))   # the header names disagree: refused either way
        adaptor.preflight(fixture.raw_zip([entry(b'EPUB/cX.xhtml')]))            # control: the same framing without a NUL is accepted

    def test_nonascii_names_without_the_utf8_flag_are_refused_early(self):
        name = 'EPUB/caf\u00e9.xhtml'
        flagged = fixture.raw_zip([(name.encode('utf-8'), b'<html/>', 0x800, 0o100644 << 16, 3)])
        adaptor.preflight(flagged)
        unflagged = fixture.raw_zip([(name.encode('utf-8'), b'<html/>', 0, 0o100644 << 16, 3)])
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.preflight(unflagged)
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_EPUB_FEATURE')
        self.assertIn('UTF-8 flag', caught.exception.fault.message)
        adaptor.preflight(fixture.raw_zip([(b'EPUB/plain.xhtml', b'<html/>', 0, 0o100644 << 16, 3)]))        # ASCII needs no flag

    def test_identity_is_pinned_to_the_audited_release(self):
        for accepted in ('EPUBCheck v5.4.0', 'EPUBCheck v5.4.0\n'):
            self.assertEqual(adaptor.check_identity(accepted), 'EPUBCheck v5.4.0')
        for refused in ('EPUBCheck v5.4.1\n', 'EPUBCheck v5.4.10\n', 'EPUBCheck v5.5.0\n', 'EPUBCheck v5.3.0\n', 'EPUBCheck v5.4\n', 'EPUBCheck v5.4.0-rc1\n'):
            self.assertEqual(fault_code(lambda: adaptor.check_identity(refused)), 'UNSUPPORTED_RUNTIME', refused)

    def test_report_with_a_spine_item_lacking_an_index_is_an_invalid_report_not_a_crash(self):
        facts = adaptor.preflight(fixture.valid())
        report = json.loads(json.dumps(adaptor.parse_report(json.dumps(self.report_for(fixture.valid())).encode(), 'EPUBCheck v5.4.0')))
        adaptor.bind_items(report, facts, 'x')
        for item in report['items']:
            if item['isSpineItem']:
                item['spineIndex'] = None
        self.assertEqual(fault_code(lambda: adaptor.bind_items(report, facts, 'x')), 'EPUBCHECK_REPORT_INVALID')

    def report_for(self, data):
        import epubcheck_fake
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [i.filename for i in archive.infolist() if not i.is_dir()]
            sizes = {i.filename: (i.compress_size, i.file_size, 'Stored' if i.compress_type == 0 else 'Deflated') for i in archive.infolist()}
        return epubcheck_fake.report(names, sizes, {}, 'captured.epub')


class Lifecycle(Base):
    def test_accepted_publication_runs_and_verifies(self):
        directory = self.run_epub(fixture.valid())
        self.assertEqual(sorted(p.name for p in directory.iterdir() if p.name != '.dispatch' and not p.name.endswith('.metadata.json')),
                         sorted(adaptor.evidence_names() | {'assessment.json', 'epubcheck-summary.json', 'verification.json', 'result.json', 'schema.snapshot.json', 'publication-metadata.json'}))
        result = json.loads((directory / 'result.json').read_text())
        self.assertEqual((result['status'], result['verified'], result['artifacts']), ('succeeded', True, 2))
        self.assertEqual(result['checker']['counts'], {'fatal': 0, 'error': 0, 'warning': 0, 'usage': 0, 'info': 0})
        self.assertEqual(result['source']['members'], 5)
        summary = json.loads((directory / 'epubcheck-summary.json').read_text())
        self.assertEqual(summary['source']['sha256'], hashlib.sha256((directory / 'captured.epub').read_bytes()).hexdigest())
        self.assertEqual(self.verify(directory)['verified'], True)
        argv = json.loads((directory / 'check-submission.json').read_text())
        self.assertEqual(argv['exitCode'], 0)
        self.assertIn('--failonwarnings', (directory / 'check-launcher.py').read_text())
        self.assertIn("{'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=true'}", (directory / 'check-launcher.py').read_text())
        self.assertNotIn('PATH', (directory / 'check-launcher.py').read_text())
        for stage in ('version', 'check'):
            self.assertEqual((directory / (stage + '.stderr')).read_text(), NOTICE)

    def test_rejection_publishes_nothing_and_keeps_findings(self):
        data = scripted(messages=[message('RSC-005', 'ERROR'), message('OPF-053', 'WARNING', path=None)])
        directory = self.root / 'rejected'
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(self.document(data), directory, executable=str(self.launcher), timeout=60)
        fault = caught.exception.fault
        self.assertEqual(fault.code, 'EPUBCHECK_REJECTED')
        self.assertEqual(fault.observed['findings']['counts'], {'fatal': 0, 'error': 1, 'warning': 1, 'usage': 0, 'info': 0})
        self.assertEqual([m['id'] for m in fault.observed['findings']['messages']], ['RSC-005', 'OPF-053'])
        names = {p.name for p in directory.iterdir()}
        self.assertTrue({'rejected-assessment.json', 'captured.epub', 'check-submission.json'} <= names)
        self.assertFalse(names & {'assessment.json', 'epubcheck-summary.json', 'verification.json', 'publication-metadata.json'})
        self.assertEqual(json.loads((directory / 'result.json').read_text())['status'], 'failed')
        self.assertEqual(json.loads((directory / 'check-submission.json').read_text())['exitCode'], 1)
        self.rejects(directory, 'INCOMPLETE_EXECUTION')

    def test_informational_messages_do_not_reject_but_are_listed(self):
        directory = self.run_epub(scripted(messages=[message('INF-001', 'INFO', 'under review'), message('OPF-099', 'USAGE', 'usage note')]))
        summary = json.loads((directory / 'epubcheck-summary.json').read_text())
        self.assertEqual([m['id'] for m in summary['checker']['informational']], ['INF-001', 'OPF-099'])
        self.assertEqual(summary['checker']['counts'], {'fatal': 0, 'error': 0, 'warning': 0, 'usage': 1, 'info': 1})

    def test_fatal_only_publication_is_rejected(self):
        self.assertEqual(fault_code(lambda: self.run_epub(scripted(messages=[message('RSC-016', 'FATAL')]))), 'EPUBCHECK_REJECTED')

    def test_distinct_native_failures(self):
        cases = {
            'exit-one-without-report': (dict(exit=1, **{'no-report': True}), 'NATIVE_EXECUTION_FAILED'),
            'java-loader': (dict(exit=1, stderr='Error: Could not find or load main class\n', **{'no-report': True}), 'NATIVE_UNAVAILABLE'),
            'memory': (dict(exit=1, stderr='java.lang.OutOfMemoryError: Java heap space\n', **{'no-report': True}), 'NATIVE_RESOURCE_EXHAUSTED'),
            'crash-exit': (dict(exit=2, **{'no-report': True}), 'NATIVE_EXECUTION_FAILED'),
            'exit-zero-with-errors': (dict(messages=[message()], exit=0), 'EPUBCHECK_REPORT_INVALID'),
            'exit-one-clean': (dict(exit=1), 'EPUBCHECK_REPORT_INVALID'),
            'malformed': (dict(raw='{"messages": ['), 'EPUBCHECK_REPORT_INVALID'),
            'duplicate-key': (dict(raw='{"messages": [], "messages": []}'), 'EPUBCHECK_REPORT_INVALID'),
            'not-finite': (dict(raw='{"messages": NaN}'), 'EPUBCHECK_REPORT_INVALID'),
            'wrong-release': (dict(version='5.3.0'), 'EPUBCHECK_REPORT_INVALID'),
        }
        for name, (script, code) in cases.items():
            with self.subTest(name):
                self.assertEqual(fault_code(lambda: self.run_epub(scripted(**script))), code)

    def test_report_types_and_counts_are_closed(self):
        edits = {
            'bool-count': [[['checker', 'nError'], True]],
            'float-count': [[['checker', 'nWarning'], 0.0]],
            'string-count': [[['checker', 'nFatal'], '0']],
            'negative-count': [[['checker', 'nUsage'], -1]],
            'bad-path': [[['checker', 'path'], './other.epub']],
            'custom-messages': [[['customMessageFileName'], 'x.txt']],
            'extra-key': [[['extra'], 1]],
            'publication-type': [[['publication', 'isScripted'], 0]],
            'publication-key': [[['publication', 'novel'], 1]],
            'item-size': [[['items', 0, 'uncompressedSize'], 7]],
            'item-name': [[['items', 0, 'fileName'], 'EPUB/ghost.xhtml']],
            'nspines': [[['publication', 'nSpines'], 3]],
            'messages-mismatch': [[['checker', 'nError'], 1]],
            'message-severity': [[['messages'], [dict(message(), severity='NOTICE')]]],
            'message-extra': [[['messages'], [dict(message(), extra=1)]]],
            'message-id': [[['messages'], [dict(message(), ID='bad')]]],
        }
        for name, edit in edits.items():
            with self.subTest(name):
                self.assertEqual(fault_code(lambda: self.run_epub(scripted(edits=edit))), 'EPUBCHECK_REPORT_INVALID', name)

    def test_existing_output_and_bad_timeout_and_missing_source(self):
        directory = self.run_epub(fixture.valid())
        self.assertEqual(fault_code(lambda: adaptor.run(self.document(fixture.valid()), directory, executable=str(self.launcher))), 'OUTPUT_EXISTS')
        for timeout in (0, -1, float('nan'), float('inf'), True, 7200):
            self.assertEqual(fault_code(lambda: adaptor.run(self.document(fixture.valid()), self.root / 'never', executable=str(self.launcher), timeout=timeout)),
                             'INVALID_ARGUMENT' if timeout is not True else 'INVALID_ARGUMENT')
        document = {'version': adaptor.VERSION, 'operation': 'validate', 'source': str(self.root / 'absent.epub')}
        self.assertEqual(fault_code(lambda: adaptor.run(document, self.root / 'o2', executable=str(self.launcher))), 'INVALID_EPUB_SOURCE')

    def test_unavailable_launcher_is_not_a_checker_verdict(self):
        broken = self.root / 'broken'
        broken.write_text('#!/bin/sh\nexec /nonexistent/java "$@"\n')
        broken.chmod(0o755)
        self.assertEqual(fault_code(lambda: self.run_epub(fixture.valid(), executable=str(broken))), 'NATIVE_UNAVAILABLE')
        wrong = self.root / 'wrong'
        wrong.write_text('#!/bin/sh\necho "EPUBCheck v4.2.6"\n')
        wrong.chmod(0o755)
        self.assertEqual(fault_code(lambda: self.run_epub(fixture.valid(), executable=str(wrong))), 'UNSUPPORTED_RUNTIME')

    def test_timeout_leaves_no_native_worker(self):
        pid_file = self.root / 'pid'
        data = scripted(sleep=30, **{'pid-file': str(pid_file)})
        started = time.monotonic()
        self.assertEqual(fault_code(lambda: self.run_epub(data, timeout=3)), 'RUNNER_TIMED_OUT')
        self.assertLess(time.monotonic() - started, 20)
        pid = int(pid_file.read_text())
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_cancellation_leaves_no_native_worker(self):
        from schemaxis.dispatch import allocation
        pid_file = self.root / 'pid'
        data = scripted(sleep=30, **{'pid-file': str(pid_file)})
        cancel = threading.Event()
        threading.Timer(2.0, cancel.set).start()
        with allocation({'threads': 2}, cancel):
            self.assertEqual(fault_code(lambda: self.run_epub(data, timeout=60)), 'RUNNER_CANCELLED')
        pid = int(pid_file.read_text())
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_captured_bytes_changing_during_the_check_are_refused(self):
        data = scripted(sleep=3)
        directory = self.root / 'race'

        def swap():
            time.sleep(1.5)
            (directory / 'captured.epub').write_bytes(fixture.valid())
        thread = threading.Thread(target=swap)
        thread.start()
        try:
            self.assertEqual(fault_code(lambda: adaptor.run(self.document(data), directory, executable=str(self.launcher), timeout=60)), 'VERIFICATION_FAILED')
        finally:
            thread.join()
        self.assertEqual(json.loads((directory / 'result.json').read_text())['status'], 'failed')

    def test_source_changes_after_capture_do_not_affect_verification(self):
        document = self.document(fixture.valid())
        directory = self.root / 'late'
        adaptor.run(document, directory, executable=str(self.launcher), timeout=60)
        Path(document['source']).write_bytes(b'replaced afterwards')
        self.assertTrue(self.verify(directory)['verified'])


class Trust(Base):
    def test_resolution_order_and_refusals(self):
        with private_configuration():
            self.assertEqual(fault_code(lambda: adaptor.runtime()), 'INTERPRETER_NOT_FOUND')
            for value in ('relative/launcher', str(self.root / 'absent'), str(self.root)):
                self.assertEqual(fault_code(lambda: adaptor.runtime(value)), 'INTERPRETER_NOT_FOUND')
            plain = self.root / 'plain'
            plain.write_text('x')
            self.assertEqual(fault_code(lambda: adaptor.runtime(str(plain))), 'INTERPRETER_NOT_FOUND')
            self.assertEqual(adaptor.runtime(str(self.launcher)), {'epubcheck': str(self.launcher)})
            os.environ['SCHEMAXIS_EPUBCHECK'] = str(self.launcher)
            self.assertEqual(adaptor.runtime(), {'epubcheck': str(self.launcher)})
            other = self.root / 'other'
            other.write_text('#!/bin/sh\n')
            other.chmod(0o755)
            self.assertEqual(adaptor.runtime(str(other)), {'epubcheck': str(other)})   # an explicit argument wins over the environment
        with private_configuration({'epubcheck': str(self.launcher)}):
            self.assertEqual(adaptor.runtime(), {'epubcheck': str(self.launcher)})

    def test_path_is_never_searched(self):
        directory = self.root / 'bin'
        directory.mkdir()
        (directory / 'epubcheck').write_text('#!/bin/sh\necho EPUBCheck v5.4.0\n')
        (directory / 'epubcheck').chmod(0o755)
        with private_configuration(), mock.patch.dict(os.environ, {'PATH': str(directory)}):
            self.assertEqual(fault_code(lambda: adaptor.runtime()), 'INTERPRETER_NOT_FOUND')

    def test_verify_without_launcher_is_a_fault_not_a_skip(self):
        directory = self.run_epub(fixture.valid())
        with private_configuration():
            self.assertEqual(fault_code(lambda: adaptor.verify(directory)), 'INTERPRETER_NOT_FOUND')
        with private_configuration({'epubcheck': str(self.launcher)}):
            self.assertTrue(adaptor.verify(directory)['verified'])

    def test_receipt_executable_is_never_launched(self):
        directory = self.run_epub(fixture.valid())
        marker = self.root / 'marker'
        trap = self.root / 'trap'
        trap.write_text('#!/bin/sh\ntouch %s\n' % marker)
        trap.chmod(0o755)
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['executables'] = {'epubcheck': str(trap)}
        (directory / 'verification.json').write_text(json.dumps(receipt))
        self.rejects(directory)
        self.assertFalse(marker.exists())
        for value in (['/x'], 'relative', {'epubcheck': 'relative'}, {'epubcheck': 1}, {'other': '/x'}):
            receipt['executables'] = value
            (directory / 'verification.json').write_text(json.dumps(receipt))
            self.rejects(directory)


class Tampering(Base):
    def setUp(self):
        super().setUp()
        self.directory = self.run_epub(fixture.valid())

    def edit_json(self, name, change, refresh=True):
        path = self.directory / name
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value, indent=2))
        if refresh:
            self.refresh(self.directory)

    def test_forged_assessment_fields_with_refreshed_hashes(self):
        forgeries = {
            'title': lambda r: r['publication'].__setitem__('title', 'Forged'),
            'version': lambda r: r['publication'].__setitem__('ePubVersion', '2.0'),
            'chars': lambda r: r['publication'].__setitem__('charsCount', 99999),
            'item-checksum': lambda r: r['items'][0].__setitem__('checkSum', 'ff'),
            'spine': lambda r: r['items'][0].__setitem__('isLinear', not r['items'][0]['isLinear']),
            'message-injected': lambda r: (r['messages'].append(message(severity='INFO')), None)[1],
            'counter-and-message': lambda r: (r['messages'].append(message('RSC-005', 'ERROR')), r['checker'].__setitem__('nError', 1))[1],
            'counter-only': lambda r: r['checker'].__setitem__('nWarning', 1),
            'bool-count': lambda r: r['checker'].__setitem__('nFatal', False),
            'extra-key': lambda r: r.__setitem__('extra', 1),
            'path': lambda r: r['checker'].__setitem__('path', './elsewhere.epub'),
        }
        for name, change in forgeries.items():
            with self.subTest(name):
                self.edit_json('assessment.json', change)
                self.rejects(self.directory)
                self.directory = self.run_epub(fixture.valid())

    def test_only_the_documented_volatile_fields_are_excluded_from_the_comparison(self):
        report = json.loads((self.directory / 'assessment.json').read_text())
        changed = copy.deepcopy(report)
        changed['checker'].update(checkDate='01-01-2000 00:00:00', elapsedTime=1)
        self.assertEqual(adaptor.stable(report), adaptor.stable(changed))
        self.assertEqual(adaptor.VOLATILE, ('checkDate', 'elapsedTime'))
        for key in report['checker']:
            if key not in adaptor.VOLATILE:
                other = copy.deepcopy(report)
                other['checker'][key] = 'x'
                self.assertNotEqual(adaptor.stable(report), adaptor.stable(other), key)
        self.assertNotEqual(report['checker']['checkDate'], '01-01-2000 00:00:00')
        self.assertTrue(self.verify(self.directory)['verified'])    # the fresh check differs in checkDate and elapsedTime alone

    def test_malformed_retained_json_with_refreshed_hashes(self):
        for name in ('assessment.json', 'epubcheck-summary.json', 'authored.json', 'plan.json', 'captures.json', 'result.json', 'check-inputs.json'):
            with self.subTest(name):
                directory = self.run_epub(fixture.valid())
                path = directory / name
                original = path.read_text()
                for text in ('{', original.replace('{', '{"dup": 1, "dup": 2,', 1), original.replace('{', '{"n": NaN,', 1), '﻿' + original, '[]'):
                    path.write_text(text)
                    self.refresh(directory)
                    self.assertIn(fault_code(lambda: self.verify(directory)), ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION', 'INVALID_SCHEMA_SNAPSHOT'), (name, text[:20]))
                self.assertEqual(path.exists(), True)

    def test_forged_summary_and_result_claims(self):
        self.edit_json('epubcheck-summary.json', lambda s: s['checker']['counts'].__setitem__('error', 0) or s['source'].__setitem__('members', 6))
        self.rejects(self.directory)
        for name, change in {'members': lambda r: r['source'].__setitem__('members', 9), 'verified-int': lambda r: r.__setitem__('verified', 1),
                             'counts': lambda r: r['checker']['counts'].__setitem__('error', 1), 'extra': lambda r: r.__setitem__('extra', True),
                             'missing': lambda r: r.pop('artifacts'), 'status': lambda r: r.__setitem__('status', 'failed'),
                             'fresh-identity': lambda r: r['runtime'].__setitem__('freshCheck', 'EPUBCheck v9.9.9'),
                             'recorded-identity': lambda r: r['runtime'].__setitem__('epubcheck', 'EPUBCheck v5.4.9')}.items():
            with self.subTest(name):
                directory = self.run_epub(fixture.valid())
                path = directory / 'result.json'
                value = json.loads(path.read_text())
                change(value)
                path.write_text(json.dumps(value))
                self.rejects(directory, 'INCOMPLETE_EXECUTION' if name == 'status' else 'VERIFICATION_FAILED')

    def test_replaced_capture_with_refreshed_hashes(self):
        for name, data in (('other-valid', fixture.rich()), ('defective', fixture.valid() + b'x'), ('garbage', b'junk')):
            with self.subTest(name):
                directory = self.run_epub(fixture.valid())
                (directory / 'captured.epub').write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                captures = json.loads((directory / 'captures.json').read_text())
                captures.update(bytes=len(data), sha256=digest)
                (directory / 'captures.json').write_text(json.dumps(captures))
                self.refresh(directory)
                self.rejects(directory)

    def test_fresh_check_that_rejects_the_held_bytes_fails_verification(self):
        directory = self.run_epub(scripted(messages=[]))
        data = scripted(messages=[message('OPF-053', 'WARNING')])
        (directory / 'captured.epub').write_bytes(data)
        captures = json.loads((directory / 'captures.json').read_text())
        captures.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (directory / 'captures.json').write_text(json.dumps(captures))
        self.refresh(directory)
        try:
            self.verify(directory)
        except SchemaxisError as error:
            self.assertEqual(error.fault.code, 'VERIFICATION_FAILED')
            self.assertEqual(error.fault.observed['findings']['counts']['warning'], 1)
        else:
            self.fail('a rejected capture verified')

    def test_evidence_membership_and_receipt_tampering(self):
        for name in sorted(adaptor.evidence_names()):
            with self.subTest('append ' + name):
                directory = self.run_epub(fixture.valid())
                with (directory / name).open('ab') as stream:
                    stream.write(b' ')
                self.rejects(directory)
        directory = self.run_epub(fixture.valid())
        (directory / 'stray.txt').write_text('extra')
        self.rejects(directory)
        directory = self.run_epub(fixture.valid())
        (directory / 'epubcheck-summary.json').unlink()
        self.rejects(directory)
        directory = self.run_epub(fixture.valid())
        (directory / 'assessment.json').unlink()
        self.rejects(directory)
        directory = self.run_epub(fixture.valid())
        (directory / 'version.stdout').write_text('EPUBCheck v5.4.1\n')
        self.refresh(directory)
        self.rejects(directory)
        directory = self.run_epub(fixture.valid())
        (directory / 'check.stderr').write_text('noise')
        self.refresh(directory)
        self.rejects(directory)
        directory = self.run_epub(fixture.valid())
        (directory / 'check-launcher.py').write_text((directory / 'check-launcher.py').read_text().replace('--quiet', '--verbose'))
        self.refresh(directory)
        self.rejects(directory)
        directory = self.run_epub(fixture.valid())
        submission = json.loads((directory / 'check-submission.json').read_text())
        submission['exitCode'] = 1
        (directory / 'check-submission.json').write_text(json.dumps(submission))
        self.refresh(directory)
        self.rejects(directory)

    def test_symlinked_or_special_files_are_refused(self):
        os.remove(self.directory / 'captured.epub')
        os.symlink(self.source(fixture.valid()), self.directory / 'captured.epub')
        self.rejects(self.directory)

    def test_unfinished_and_failed_results_do_not_verify(self):
        (self.directory / 'result.json').write_text(json.dumps({'status': 'incomplete', 'verified': False}))
        self.rejects(self.directory, 'INCOMPLETE_EXECUTION')

    def test_typed_comparison_is_not_python_equality(self):
        self.assertFalse(adaptor.same_json({'a': 1}, {'a': True}))
        self.assertFalse(adaptor.same_json({'a': 1}, {'a': 1.0}))
        self.assertTrue(adaptor.same_json({'a': [1, 2], 'b': None}, {'b': None, 'a': [1, 2]}))


class Sandbox(Base):
    def observed_environment(self, env_file):
        return {k: v for k, v in json.loads(env_file.read_text()).items() if k not in ('PWD', 'SHLVL', '_', 'OLDPWD')}    # the shell wrapper adds these

    def test_native_environment_is_minimal_and_cpu_bounded(self):
        launcher_text = adaptor.launcher('check', [adaptor.CAPTURE], ['/x/launcher', 'a'], adaptor.MAX_REPORT_BYTES)
        self.assertIn('os.execve(command[0],command,%r)' % FIXED_ENVIRONMENT, launcher_text)
        self.assertIn('RLIMIT_CPU', launcher_text)
        self.assertIn('RLIMIT_FSIZE', launcher_text)
        self.assertIn('sched_setaffinity', launcher_text)
        self.assertIn('[:2]', launcher_text)
        self.assertIn('os._exit(127)', launcher_text)
        env_file = self.root / 'env.json'
        with mock.patch.dict(os.environ, POISONED_ENVIRONMENT):
            directory = self.run_epub(scripted(**{'env-file': str(env_file)}))
            self.assertEqual(self.observed_environment(env_file), FIXED_ENVIRONMENT)     # the check stage, then the fresh check inside run
            env_file.unlink()
            self.assertTrue(self.verify(directory)['verified'])
            self.assertEqual(self.observed_environment(env_file), FIXED_ENVIRONMENT)     # the fresh check of a separate verify call

    def test_every_generated_stage_launcher_passes_exactly_the_fixed_environment(self):
        probe = 'import json,os,sys;json.dump(dict(os.environ),open(sys.argv[1],"w"))'
        for stage, names in (('version', []), ('check', [adaptor.CAPTURE])):
            work = self.root / stage
            work.mkdir()
            (work / adaptor.CAPTURE).write_bytes(fixture.valid())
            out = work / 'env.json'
            (work / 'launcher.py').write_text(adaptor.launcher(stage, names, [sys.executable, '-c', probe, str(out)], adaptor.OUTPUT_SLACK))
            environment = {**POISONED_ENVIRONMENT, 'PATH': os.environ.get('PATH', '')}
            subprocess.run([sys.executable, str(work / 'launcher.py')], cwd=work, env=environment, check=True, capture_output=True, timeout=60)
            self.assertEqual(json.loads(out.read_text()), FIXED_ENVIRONMENT, stage)

    def test_a_launcher_that_does_not_apply_the_offline_policy_is_refused(self):
        notice = 'Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=true'
        for label, stderr in (('dropped', ''), ('other-property', 'Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=false\n'), ('extra-line', notice + '\nWARNING: x\n'),
                              ('prefixed', 'note\n' + notice + '\n'), ('wrong-case', notice.lower() + '\n'), ('no-newline', notice)):
            path = self.root / label
            path.write_text('#!/bin/sh\necho "EPUBCheck v5.4.0"\nprintf %%s \'%s\' >&2\n' % stderr)      # byte-exact stderr, newlines included
            path.chmod(0o755)
            with self.assertRaises(SchemaxisError) as caught:
                self.run_epub(fixture.valid(), executable=str(path))
            self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_RUNTIME', label)
            self.assertIn('offline policy', caught.exception.fault.message, label)
            self.assertEqual(caught.exception.fault.location, 'version', label)
        exact = self.root / 'exact'      # control: the same script shape with exactly the notice is accepted as an identity stage
        exact.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "EPUBCheck v5.4.0"; printf %%s \'%s\n\' >&2; exit 0; fi\nexec %s %s "$@"\n' % (notice, sys.executable, FAKE))
        exact.chmod(0o755)
        directory = self.run_epub(fixture.valid(), executable=str(exact))
        self.assertTrue(adaptor.verify(directory, executable=str(exact))['verified'])

    def test_retained_offline_notice_is_verified_exactly(self):
        for stage, content in (('version', ''), ('version', NOTICE + NOTICE), ('check', ''), ('check', NOTICE + 'x\n'), ('check', 'x\n' + NOTICE)):
            directory = self.run_epub(fixture.valid())
            (directory / (stage + '.stderr')).write_text(content)
            receipt = json.loads((directory / 'verification.json').read_text())
            receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
            (directory / 'verification.json').write_text(json.dumps(receipt))
            self.assertEqual(fault_code(lambda: self.verify(directory)), 'VERIFICATION_FAILED', (stage, content))
        directory = self.run_epub(fixture.valid())
        (directory / 'check.stdout').write_text('noise')
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
        (directory / 'verification.json').write_text(json.dumps(receipt))
        self.assertEqual(fault_code(lambda: self.verify(directory)), 'VERIFICATION_FAILED')

    def test_a_receipt_from_before_the_fixed_offline_launcher_no_longer_verifies(self):
        directory = self.run_epub(fixture.valid())
        old = adaptor.launcher('check', [adaptor.CAPTURE], adaptor.stage_commands(str(self.launcher))['check'][0], adaptor.MAX_REPORT_BYTES)
        old = old.replace(repr(FIXED_ENVIRONMENT), repr({'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}))
        self.assertNotEqual(old, (directory / 'check-launcher.py').read_text())
        (directory / 'check-launcher.py').write_text(old)
        (directory / 'check.stderr').write_text('')
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
        (directory / 'verification.json').write_text(json.dumps(receipt))
        self.assertEqual(fault_code(lambda: self.verify(directory)), 'VERIFICATION_FAILED')

    def test_a_fresh_check_stage_that_logs_beyond_the_offline_notice_is_refused_before_parsing(self):
        facts = adaptor.preflight(fixture.valid())
        for label, script in (('stderr', {'stderr': 'WARNING: extra\n'}), ('stderr-without-notice-prefix', {'stderr': 'x'})):
            capture = scripted(**script)
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.fresh_check({'epubcheck': str(self.launcher)}, capture, adaptor.preflight(capture))
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED', label)
            self.assertIn('more than the fixed offline notice', caught.exception.fault.message, label)
            self.assertEqual(caught.exception.fault.location, 'check', label)
        stdout = self.root / 'noisy'
        stdout.write_text('#!/bin/sh\n[ "$1" = "--version" ] || echo noise\nexec %s %s "$@"\n' % (sys.executable, FAKE))
        stdout.chmod(0o755)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.fresh_check({'epubcheck': str(stdout)}, fixture.valid(), facts)
        self.assertIn('more than the fixed offline notice', caught.exception.fault.message)
        rejected = scripted(messages=[message()], stderr='checker summary on stderr\n')                         # a rejection (exit 1) still reports its findings, not a log complaint
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.fresh_check({'epubcheck': str(self.launcher)}, rejected, adaptor.preflight(rejected))
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        self.assertEqual(caught.exception.fault.observed['findings']['counts']['error'], 1)
        report, identity = adaptor.fresh_check({'epubcheck': str(self.launcher)}, fixture.valid(), facts)      # control: the plain launcher passes
        self.assertEqual(identity, 'EPUBCheck v5.4.0')

    def test_output_cap_overflow_is_resource_exhaustion_before_any_json_is_read(self):
        """A JVM-like checker ignores SIGXFSZ: past the cap it gets a short write, exits normally and leaves a truncated report."""
        junk = '{"messages": [' + 'x' * 6000
        for label, script in (('exit0', {'raw': junk, 'ignore-xfsz': True}), ('exit1', {'raw': junk, 'ignore-xfsz': True, 'exit': 1}), ('exit2', {'raw': junk, 'ignore-xfsz': True, 'exit': 2})):
            with mock.patch.object(adaptor, 'MAX_REPORT_BYTES', 4096):
                with self.assertRaises(SchemaxisError) as caught:
                    self.run_epub(scripted(**script))
            self.assertEqual(caught.exception.fault.code, 'NATIVE_RESOURCE_EXHAUSTED', label)
            self.assertIn('output cap', caught.exception.fault.message, label)
        with mock.patch.object(adaptor, 'MAX_REPORT_BYTES', 4096):             # control: a truncated report of the same kind under the budget is an invalid report
            self.assertEqual(fault_code(lambda: self.run_epub(scripted(raw='{"messages": [', **{'ignore-xfsz': True}))), 'EPUBCHECK_REPORT_INVALID')

    def test_kernel_file_cap_is_the_reader_budget_plus_one_byte(self):
        text = adaptor.launcher('check', [adaptor.CAPTURE], ['x'], adaptor.MAX_REPORT_BYTES)
        self.assertIn('RLIMIT_FSIZE,(%d,%d)' % (adaptor.MAX_REPORT_BYTES + 1, adaptor.MAX_REPORT_BYTES + 1), text)
        work = self.root / 'cap'
        work.mkdir()
        (work / adaptor.CAPTURE).write_bytes(b'x')
        probe = 'import os;fd=os.open("out",os.O_WRONLY|os.O_CREAT);import signal;signal.signal(signal.SIGXFSZ,signal.SIG_IGN)\ntry:\n os.write(fd,b"y"*1000)\nexcept OSError as e:\n print(e.errno)'
        (work / 'launcher.py').write_text(adaptor.launcher('check', [adaptor.CAPTURE], [sys.executable, '-c', probe], 300))
        subprocess.run([sys.executable, str(work / 'launcher.py')], cwd=work, check=True, capture_output=True, timeout=60)
        self.assertEqual((work / 'out').stat().st_size, 301)                    # budget 300 plus one: exactly one byte over the budget proves an overflow


if __name__ == '__main__':
    unittest.main()
