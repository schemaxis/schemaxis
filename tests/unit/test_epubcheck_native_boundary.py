"""Native boundary of the EPUBCheck adaptor against the official checker.

Skipped unless SCHEMAXIS_EPUBCHECK names a trusted EPUBCheck 5.4 launcher (absolute path, fixed command that starts the official
JAR with Java). The expected message identifiers come from the fixture designs in epubcheck_fixture.py, not from the adaptor.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).parent))
import epubcheck_fixture as fixture   # noqa: E402
from epubcheck_loopback import Loopback   # noqa: E402
from schemaxis.adaptors.epubcheck import adaptor   # noqa: E402
from schemaxis.core.faults import SchemaxisError   # noqa: E402

LAUNCHER = os.environ.get('SCHEMAXIS_EPUBCHECK')


@unittest.skipUnless(LAUNCHER and os.path.isabs(LAUNCHER) and os.access(LAUNCHER, os.X_OK), 'set SCHEMAXIS_EPUBCHECK to a trusted EPUBCheck 5.4 launcher')
class NativeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.n = 0

    def document(self, data):
        self.n += 1
        path = self.root / ('src%d.epub' % self.n)
        path.write_bytes(data)
        return {'version': adaptor.VERSION, 'operation': 'validate', 'source': str(path)}

    def run_epub(self, data):
        directory = self.root / ('out%d' % self.n)
        adaptor.run(self.document(data), directory, executable=LAUNCHER, timeout=120)
        return directory

    def rejected(self, data):
        directory = self.root / ('rej%d' % self.n)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(self.document(data), directory, executable=LAUNCHER, timeout=120)
        self.assertEqual(caught.exception.fault.code, 'EPUBCHECK_REJECTED')
        return directory, caught.exception.fault

    def test_valid_publications_are_accepted_and_verified_by_a_fresh_check(self):
        for maker, members, spines in ((fixture.valid, 5, 1), (fixture.rich, 8, 2)):
            directory = self.run_epub(maker())
            summary = json.loads((directory / 'epubcheck-summary.json').read_text())
            self.assertEqual((summary['source']['members'], summary['publication']['nSpines'], summary['checker']['counts']['error']), (members, spines, 0))
            self.assertEqual(summary['publication']['ePubVersion'], '3.4')
            self.assertTrue(adaptor.verify(directory, executable=LAUNCHER)['verified'])

    def test_defective_publications_are_rejected_with_independently_expected_messages(self):
        for name in ('missing_title', 'missing_image', 'bad_date', 'remote_image'):
            expected = fixture.EXPECTED[name]
            directory, fault = self.rejected(getattr(fixture, name)())
            report = json.loads((directory / 'rejected-assessment.json').read_text())
            self.assertEqual(sorted(m['ID'] for m in report['messages']), sorted(expected['ids']), name)
            counts = fault.observed['findings']['counts']
            self.assertEqual((counts['fatal'], counts['error'], counts['warning']), expected['counts'], name)
            self.assertFalse((directory / 'assessment.json').exists())

    def test_forged_assessment_with_refreshed_hashes_fails_the_fresh_native_check(self):
        directory = self.run_epub(fixture.valid())
        path = directory / 'assessment.json'
        report = json.loads(path.read_text())
        report['publication']['title'] = 'Forged'
        path.write_text(json.dumps(report, indent=2))
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['artifacts'] = adaptor.publications(directory)
        receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
        (directory / 'verification.json').write_text(json.dumps(receipt))
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(directory, executable=LAUNCHER)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_swapped_capture_is_checked_afresh(self):
        directory = self.run_epub(fixture.valid())
        data = fixture.missing_title()
        (directory / 'captured.epub').write_bytes(data)
        captures = json.loads((directory / 'captures.json').read_text())
        captures.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        (directory / 'captures.json').write_text(json.dumps(captures))
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
        (directory / 'verification.json').write_text(json.dumps(receipt))
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(directory, executable=LAUNCHER)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        self.assertEqual(caught.exception.fault.observed['findings']['counts']['error'], 4)

    def test_remote_references_cause_no_network_connection(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(8)
        listener.settimeout(0.2)
        port, hits, stop = listener.getsockname()[1], [], threading.Event()

        def serve():
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                    hits.append(1)
                    connection.close()
                except OSError:
                    pass
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            url = 'http://127.0.0.1:%d/' % port
            body = ('<p><img src="%sx.png" alt="x"/></p><p><a href="%s">link</a></p><audio src="%sa.mp3"/><video src="%sv.mp4"/>'
                    '<script src="%ss.js"></script><link rel="stylesheet" href="%ss.css"/>' % ((url,) * 6))
            self.rejected(fixture.epub(chapter_text=fixture.chapter(body)))
        finally:
            stop.set()
            thread.join()
            listener.close()
        self.assertEqual(hits, [])


@unittest.skipUnless(LAUNCHER and os.path.isabs(LAUNCHER) and os.access(LAUNCHER, os.X_OK), 'set SCHEMAXIS_EPUBCHECK to a trusted EPUBCheck 5.4 launcher')
class OfflinePolicy(unittest.TestCase):
    """Direct native probes of EPUBCheck 5.4's external DTD resolution. The host preflight refuses a loopback SYSTEM identifier, so these
    publications never enter ``adaptor.run``; they exercise the fixed stage launcher and the official checker directly. They do not show that the
    platform admits a loopback DTD."""
    NOTICE = 'Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=true\n'

    def probe(self, directory, data, environment):
        (directory / 'probe.epub').write_bytes(data)
        report = directory / 'probe.json'
        report.unlink(missing_ok=True)
        done = subprocess.run([LAUNCHER, str(directory / 'probe.epub'), '--json', str(report), '--failonwarnings', '--quiet', '--locale', 'en'], cwd=directory,
                              env=environment, capture_output=True, text=True, timeout=120)
        messages = json.loads(report.read_text())['messages'] if report.exists() else None
        return done, messages

    def test_unknown_epub2_dtd_is_fetched_without_and_never_with_the_fixed_property(self):
        server = Loopback()
        try:
            data = fixture.epub2('<!DOCTYPE html PUBLIC "-//SCHEMAXIS//DTD CANARY 1.0//EN" "http://127.0.0.1:%d/canary.dtd">' % server.port)
            self.assertEqual(self.refused_by_host(data), 'UNSUPPORTED_EPUB_FEATURE')      # the host never hands this publication to the checker
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                scratch = directory / 'fixed'
                scratch.mkdir()
                (scratch / adaptor.CAPTURE).write_bytes(data)
                poisoned = {'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=false', 'JDK_JAVA_OPTIONS': '-Depubcheck.offline=false', '_JAVA_OPTIONS': '-Depubcheck.offline=false'}
                with mock.patch.dict(os.environ, poisoned):
                    identity, code = adaptor.run_check(scratch, LAUNCHER, (0, 1))      # the fixed stage launchers, bypassing the host preflight
                self.assertEqual(identity, 'EPUBCheck v5.4.0')
                self.assertEqual(adaptor.read_log(scratch, 'version', '.stderr'), self.NOTICE)
                self.assertTrue(adaptor.read_log(scratch, 'check', '.stderr').startswith(self.NOTICE))
                self.assertEqual(code, 1)
                fixed_ids = sorted(m['ID'] for m in json.loads((scratch / adaptor.ASSESSMENT).read_text())['messages'])
                self.assertEqual(server.requests, [])                       # negative control: the fixed launcher environment closes the fallback
                before = len(server.requests)
                control, messages = self.probe(directory, data, {'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'})
                fetched = server.requests[before:]
                self.assertEqual(sorted(m['ID'] for m in messages), fixed_ids)
                if not fetched:
                    self.skipTest('positive control: this Java and checker made no request without the property; the fixed property is still applied and showed no request')
                self.assertEqual(fetched, ['GET /canary.dtd HTTP/1.1'])
                self.assertNotIn('Picked up', control.stderr)
        finally:
            server.close()

    def refused_by_host(self, data):
        try:
            adaptor.preflight(data)
        except SchemaxisError as error:
            return error.fault.code
        return None

    def test_epub3_and_catalogue_doctypes_make_no_request_with_or_without_the_property(self):
        server = Loopback()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                unknown = '<!DOCTYPE html PUBLIC "-//SCHEMAXIS//DTD CANARY 1.0//EN" "http://127.0.0.1:%d/canary.dtd">' % server.port
                catalogue = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
                for data in (fixture.epub2(unknown, 3), fixture.epub2(catalogue)):
                    for environment in ({'LANG': 'C.UTF-8'}, {'LANG': 'C.UTF-8', 'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=true'}):
                        self.probe(directory, data, environment)
        finally:
            server.close()
        self.assertEqual(server.requests, [])

    def test_accepted_run_has_exactly_the_jvm_notice_as_its_stage_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'book.epub'
            source.write_bytes(fixture.valid())
            directory = Path(tmp) / 'out'
            adaptor.run({'version': adaptor.VERSION, 'operation': 'validate', 'source': str(source)}, directory, executable=LAUNCHER, timeout=120)
            for stage in ('version', 'check'):
                self.assertEqual((directory / (stage + '.stderr')).read_text(), self.NOTICE)
            self.assertEqual((directory / 'check.stdout').read_text(), '')


@unittest.skipUnless(LAUNCHER and os.path.isabs(LAUNCHER) and os.access(LAUNCHER, os.X_OK), 'set SCHEMAXIS_EPUBCHECK to a trusted EPUBCheck 5.4 launcher')
class MediaTypeBoundary(unittest.TestCase):
    """Review 38: the checker parses a manifest member as XML by declared media type, whatever its file name. Each hostile publication is shown twice and the two
    are never conflated: (1) the HOST refusal through ``adaptor.run`` makes zero native calls (a counting wrapper launcher proves it) and no loopback request;
    (2) a DIRECT native control hands the same bytes straight to the official checker, bypassing the host, to observe what the checker itself would do. The controls use only
    a loopback listener owned by the test and a marker file the test wrote in its own temporary directory; no secret, external or public endpoint is touched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = self.root / 'calls.log'
        self.wrapper = self.root / 'counting-launcher'
        self.wrapper.write_text('#!/bin/sh\necho "$1" >> %s\nexec %s "$@"\n' % (self.calls, LAUNCHER))
        self.wrapper.chmod(0o755)
        self.n = 0

    def native_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def host_refusal(self, data):
        """Run the publication through the adaptor with the counting launcher; the fault code, and the number of native calls it made."""
        self.n += 1
        source = self.root / ('book%d.epub' % self.n)
        source.write_bytes(data)
        before = len(self.native_calls())
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run({'version': adaptor.VERSION, 'operation': 'validate', 'source': str(source)}, self.root / ('out%d' % self.n), executable=str(self.wrapper), timeout=120)
        return caught.exception.fault.code, len(self.native_calls()) - before

    def direct(self, data, environment):
        self.n += 1
        book, report = self.root / ('direct%d.epub' % self.n), self.root / ('direct%d.json' % self.n)
        book.write_bytes(data)
        done = subprocess.run([LAUNCHER, str(book), '--json', str(report), '--failonwarnings', '--quiet', '--locale', 'en'], cwd=self.root, env=environment,
                              capture_output=True, text=True, timeout=120)
        return done, sorted(m['ID'] for m in json.loads(report.read_text())['messages']) if report.exists() else None

    def test_file_dtd_in_a_mime_declared_text_or_binary_member_is_a_host_refusal_with_zero_native_calls(self):
        marker = self.root / 'owned-marker.dtd'
        missing = self.root / 'absent.dtd'
        marker.write_text('<!-- owned test marker, not a secret -->\n<!ELEMENT html ANY>\n')
        observed = {}
        for content in ('c.txt', 'c.bin'):
            for label, target in (('present', marker), ('missing', missing)):
                data = fixture.epub2('<!DOCTYPE html SYSTEM "file://%s">' % target, content=content)
                code, calls = self.host_refusal(data)
                self.assertEqual((code, calls), ('UNSUPPORTED_EPUB_FEATURE', 0), (content, label))
                done, ids = self.direct(data, {'LANG': 'C.UTF-8', 'JAVA_TOOL_OPTIONS': adaptor.OFFLINE_PROPERTY})
                observed[(content, label)] = ids
        self.assertEqual(self.native_calls(), [])
        print('OBSERVED direct native file: DTD controls under the fixed property (message ids): %r' % {'/'.join(k): v for k, v in observed.items()})
        # honest positive control: a file: DTD named by a text-named member is read by the checker (present and missing differ) -- why the host must refuse it
        self.assertNotEqual(observed[('c.txt', 'present')], observed[('c.txt', 'missing')])

    def test_jar_and_ftp_loopback_dtds_in_mime_declared_members_never_reach_the_checker(self):
        server = Loopback()
        try:
            direct = {}
            for label, identifier in (('jar-http', 'jar:http://127.0.0.1:%d/x.jar!/x.dtd'), ('ftp', 'ftp://127.0.0.1:%d/x.dtd'), ('http', 'http://127.0.0.1:%d/x.dtd')):
                data = fixture.epub2('<!DOCTYPE html SYSTEM "%s">' % (identifier % server.port), content='c.txt')
                before = len(server.requests)
                self.assertEqual(self.host_refusal(data), ('UNSUPPORTED_EPUB_FEATURE', 0), label)
                self.assertEqual(server.requests[before:], [], label)              # the host refusal made no request
                before = len(server.requests)
                self.direct(data, {'LANG': 'C.UTF-8', 'JAVA_TOOL_OPTIONS': adaptor.OFFLINE_PROPERTY})
                direct[label] = server.requests[before:]
        finally:
            server.close()
        print('OBSERVED direct native loopback requests under the fixed offline property (observation of the checker, not of the host): %r' % direct)
        self.assertEqual(direct['http'], [])                                      # the property's own, documented coverage: http identifiers only
        self.assertEqual(self.native_calls(), [])
        if not direct['jar-http']:
            self.skipTest('positive control: this Java and checker made no jar:http request under the fixed property, so the documented jar:http fetch was not observed in this run')
        self.assertEqual(len(direct['jar-http']), 1, direct['jar-http'])          # observed by the loopback server itself, not inferred from the printed log
        self.assertTrue(direct['jar-http'][0].startswith('GET /x.jar'), direct['jar-http'])

    def test_unsupported_encodings_in_a_mime_declared_member_never_reach_the_checker(self):
        body = '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body><p>x</p></body></html>'
        for label, data in (('utf-32', body.encode('utf-32')), ('ebcdic', body.encode('cp037')), ('latin1-declared', body.replace('?>', ' encoding="ISO-8859-1"?>', 1).encode())):
            book = fixture.epub2('', content='c.txt')
            self.assertEqual(self.host_refusal(fixture.replace_member(book, 'OEBPS/c.txt', data)), ('UNSUPPORTED_EPUB_FEATURE', 0), label)
        self.assertEqual(self.native_calls(), [])

    def test_review43_forms_are_host_refusals_with_zero_native_calls(self):
        """Encodings the strict profile does not read, an unlisted member that only looks like XML, ambiguous references and a NUL name: refused before any launch."""
        marker = self.root / 'owned-marker.dtd'
        marker.write_text('<!ELEMENT html ANY>\n')
        doctype = '<!DOCTYPE html SYSTEM "file://%s"><html xmlns="http://www.w3.org/1999/xhtml"/>' % marker
        declaration = '<?xml version="1.0"?>'
        for label, data in (('cp037-signature', (declaration + doctype).encode('cp037')), ('ibm037-declared', b'<?xml version="1.0" encoding="IBM037"?>' + doctype.encode('cp037')),
                            ('ucs4-2143', b''.join(b'\x00\x00' + c.encode() + b'\x00' for c in declaration + doctype)),
                            ('utf8-bom-latin1', b'\xef\xbb\xbf<?xml version="1.0" encoding="ISO-8859-1"?>' + doctype.encode())):
            book = fixture.epub2('', content='c.txt')
            self.assertEqual(self.host_refusal(fixture.replace_member(book, 'OEBPS/c.txt', data)), ('UNSUPPORTED_EPUB_FEATURE', 0), label)
            self.assertEqual(self.host_refusal(fixture.with_member(fixture.valid(), 'EPUB/unlisted.bin', data)), ('UNSUPPORTED_EPUB_FEATURE', 0), label)
        for reference in ('sub\\c.txt', 'c&#9;.txt', 'c&#10;.txt'):
            book = fixture.epub2('', content='c.txt')
            changed = fixture.replace_member(book, 'OEBPS/content.opf', zipfile.ZipFile(io.BytesIO(book)).read('OEBPS/content.opf').replace(b'href="c.txt"', ('href="%s"' % reference).encode()))
            self.assertEqual(self.host_refusal(changed), ('UNSUPPORTED_EPUB_FEATURE', 0), reference)
        nul = fixture.raw_zip([(b'EPUB/c\x00.xhtml', b'<html/>', 0, 0o100644 << 16, 3)])
        self.assertEqual(self.host_refusal(nul), ('UNSAFE_EPUB_ARCHIVE', 0))
        self.assertEqual(self.native_calls(), [])

    def test_report_overflow_of_a_small_cap_is_classified_before_any_json_with_the_real_java(self):
        """The real checker under a deliberately tiny cap (2048 bytes, never a large file): the JVM ignores SIGXFSZ, so the report is cut short, not a signal exit."""
        self.n += 1
        source = self.root / 'book.epub'
        source.write_bytes(fixture.valid())
        directory = self.root / 'capped'
        with mock.patch.object(adaptor, 'MAX_REPORT_BYTES', 2048):
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run({'version': adaptor.VERSION, 'operation': 'validate', 'source': str(source)}, directory, executable=LAUNCHER, timeout=120)
        self.assertEqual(caught.exception.fault.code, 'NATIVE_RESOURCE_EXHAUSTED')
        self.assertEqual((directory / adaptor.ASSESSMENT).stat().st_size, 2049)     # budget plus the one byte that proves the overflow
        submission = json.loads((directory / 'check-submission.json').read_text()) if (directory / 'check-submission.json').exists() else {}
        print('OBSERVED real-Java small-cap probe: cap 2049 bytes, report size %d, check exit %r' % ((directory / adaptor.ASSESSMENT).stat().st_size, submission.get('exitCode', 'classified before submission record')))


if __name__ == '__main__':
    unittest.main()
